import hmac
import secrets
import time
import traceback
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote, urlencode

import httpx
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import (
    FileResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
)
from fastapi.staticfiles import StaticFiles

from backend.config import settings
from backend.models.schemas import ScoutRequest, ScoutResponse
from backend.pipeline.researcher import InsufficientEvidenceError, ResearchPipeline
from backend.services.cache import BriefCache
from backend.services.jobs import STAGE_LABELS, TOTAL_STAGES, JobStore
from backend.services.llm import ModelOverloadedError, QuotaExhaustedError
from backend.services.search import SearchQuotaExhaustedError
from backend.services import (
    auth, db, mailer, monitoring, notes, outreach, password_reset,
    pdf_export, store, tavily_usage, users,
)
from backend.services.apollo import is_configured as apollo_configured
from backend.services import hunter
from backend.services.report import brief_to_markdown
from backend.services.usage import usage

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

# Before the app is constructed, so failures during start-up are reported too.
monitoring.init()

app = FastAPI(
    title="Company Scout",
    description="AI-powered company intelligence and opportunity assessment",
    version="0.3.0",
)

app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

executor = ThreadPoolExecutor(max_workers=2)

# Paths that stay reachable without signing in.
#
# The share links are the important entry here. Sharing a finished brief is
# what the product is for, and a login wall in front of /r/{key} would break
# the one thing a reader is meant to do with one. The explainer page is public
# for the same reason: it is how someone decides whether to ask for access.
#
# /usage and /usage-page are here too, deliberately: they predate the session
# login and already carry their own gate — a separate admin token, checked in
# the route itself, returning 404 rather than 401 so the page does not even
# admit it exists. Stacking the session wall on top of that would not add
# security (the token is the real secret either way) and would break the
# "open the link with ?key= once" flow that page was built around, along
# with any server-side check of it that has no browser session to carry.
PUBLIC_PREFIXES = ("/static/", "/r/", "/report/", "/compare")
PUBLIC_PATHS = {
    "/login", "/signup", "/logout", "/health", "/about", "/favicon.ico",
    "/usage", "/usage-page", "/forgot-password", "/reset-password",
    "/use-cases", "/auth/google", "/auth/google/callback",
    "/privacy", "/terms",
}


@app.middleware("http")
async def require_sign_in(request: Request, call_next):
    """Send anyone without a session to the sign-in page.

    Inert until AUTH_PASSWORD is set, so deploying this cannot lock anybody
    out of their own site — including in local development, where there is no
    password and everything behaves exactly as before.
    """
    path = request.url.path
    public = path in PUBLIC_PATHS or path.startswith(PUBLIC_PREFIXES)

    if not public and not auth.is_signed_in(request):
        # An API call gets a status it can act on; a browser gets the door,
        # carrying where it was headed so the trip resumes after sign-in.
        if request.headers.get("accept", "").startswith("application/json"):
            return JSONResponse({"detail": "Sign in required"}, status_code=401)
        return RedirectResponse(f"/login?next={quote(path)}", status_code=303)

    response = await call_next(request)

    # The app shell and every static asset are served with no Cache-Control
    # at all otherwise, so a browser's own heuristic decides how long to
    # trust an old copy without even asking the server first. That has
    # already cost two rounds of "I can't find the button" after a real
    # deploy (outreach, then re-scout) that turned out to be a stale local
    # copy, not a missed push. `no-cache` still lets the browser reuse its
    # copy on a 304 when nothing changed -- it just has to ask each time
    # rather than assume.
    if path == "/" or path.startswith(("/static/", "/r/")):
        response.headers["Cache-Control"] = "no-cache"

    return response

# The Gemini free tier caps out at 20 requests/day total, so a handful of
# visitors can exhaust it. This limits any single visitor to a few runs
# per hour rather than trying to be a general-purpose rate limiter.
RATE_LIMIT_MAX_REQUESTS = 5
RATE_LIMIT_WINDOW_SECONDS = 3600
_request_log: dict[str, list[float]] = defaultdict(list)


def _check_rate_limit(client_ip: str) -> None:
    now = time.monotonic()
    window_start = now - RATE_LIMIT_WINDOW_SECONDS
    timestamps = [t for t in _request_log[client_ip] if t > window_start]
    if len(timestamps) >= RATE_LIMIT_MAX_REQUESTS:
        raise HTTPException(
            status_code=429,
            detail="Too many requests. Please wait a while before scouting another company.",
        )
    timestamps.append(now)
    _request_log[client_ip] = timestamps


@app.get("/")
async def index():
    return FileResponse(str(FRONTEND_DIR / "index.html"))


cache = BriefCache()
jobs = JobStore()

# Counters share the brief cache's backend. On Render that is Key Value, which
# outlives the deploys and idle spin-downs that would otherwise reset the
# day's usage to zero several times an hour.
usage.attach_store(cache.backend)

# At start-up, not on first write: a database problem should appear in
# the deploy log, not three minutes into somebody's research run.
store.ensure_schema()

print(f"[startup] Google OAuth: {'enabled' if (settings.google_client_id and settings.google_client_secret) else 'OFF — set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET'}", flush=True)


def _run_job(job_id: str, query: str, force: bool = False) -> None:
    """Run a scout to completion, recording progress against the job.

    Runs on a worker thread, so nothing here may raise into the caller: every
    outcome is written back onto the job for the client to poll.
    """
    def progress(stage: int, message: str) -> None:
        jobs.update(job_id, stage=stage, message=message)

    try:
        pipeline = ResearchPipeline()
        pipeline.research(query, progress=progress, force=force)
        jobs.update(
            job_id,
            status="done",
            stage=TOTAL_STAGES,
            message="Report ready",
        )
    except InsufficientEvidenceError as e:
        jobs.update(
            job_id,
            status="error",
            error_kind="no_evidence",
            error=str(e),
        )
    except SearchQuotaExhaustedError as e:
        # Its own error kind, so the page can name the real cause. Told it was
        # a generic failure, the obvious next move is to try again — which
        # cannot work and burns another minute finding that out.
        print(f"[scout] Tavily plan exhausted for query: {query}", flush=True)
        jobs.update(
            job_id,
            status="error",
            error_kind="search_quota_exhausted",
            error=str(e),
        )
    except QuotaExhaustedError as e:
        # Expected often enough on the free tier to deserve its own message
        # rather than a generic failure.
        print(f"[scout] Quota exhausted for query: {query}", flush=True)
        jobs.update(
            job_id,
            status="error",
            error_kind="quota_exhausted",
            error=str(e),
        )
    except ModelOverloadedError as e:
        # Google's capacity, not ours — the daily allowance is untouched, and
        # a retry in a few minutes has a real chance of working. Distinct from
        # quota_exhausted so the page can say so rather than implying a wait
        # until tomorrow. The pipeline checkpoints before scoring, which is
        # where this has been observed to happen, so a retry of the same
        # query is usually one call, not the whole run again.
        print(f"[scout] Every Gemini model reported high demand for: {query}",
              flush=True)
        monitoring.warn("Gemini reported high demand on every model",
                        query=query)
        jobs.update(
            job_id,
            status="error",
            error_kind="model_overloaded",
            error=str(e),
        )
    except Exception as e:
        print(f"ERROR in scout job: {traceback.format_exc()}", flush=True)
        # Caught so the user sees a clean message; reported because a generic
        # apology on screen is not a record anyone can act on.
        monitoring.capture(e, stage="scout_job", query=query)
        jobs.update(
            job_id,
            status="error",
            error_kind="failed",
            error="Something went wrong while researching this company. Please try again.",
        )


@app.post("/scout")
async def scout_company(request: ScoutRequest, http_request: Request):
    query = request.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Company name or URL required")

    share_key = cache.key_for(query)

    # Serve cache hits before rate limiting: they cost no API quota, so there
    # is nothing to protect against, and counting them would punish the exact
    # behaviour we want to encourage. force_refresh explicitly asks to skip
    # this — the saved report is exactly what the caller wants to replace.
    cached = None if request.force_refresh else cache.get(query)
    if cached is not None:
        return JSONResponse(
            content={
                "status": "done",
                "share_key": share_key,
                "result": ScoutResponse(
                    brief=cached,
                    duration_seconds=cached.duration_seconds,
                    share_key=share_key,
                ).model_dump(mode="json"),
            }
        )

    # A forced re-run spends real quota the same as any other fresh scout,
    # so it counts against the same rate limit rather than bypassing it.
    _check_rate_limit(http_request.client.host if http_request.client else "unknown")

    # A scout takes minutes, and the proxy in front of this app abandons any
    # request left unanswered for ~100 seconds. So hand back a job to poll
    # rather than holding the connection open and losing it.
    job = jobs.create(query, share_key=share_key)
    executor.submit(_run_job, job.id, query, force=request.force_refresh)

    return JSONResponse(status_code=202, content={"status": "running", **job.as_dict()})


@app.get("/scout/status/{job_id}")
async def scout_status(job_id: str):
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(
            status_code=404,
            detail="That research job has expired. Please scout the company again.",
        )

    payload = job.as_dict()

    # Attach the finished brief so the client needs only this one endpoint.
    if job.status == "done" and job.share_key:
        brief = cache.get_by_key(job.share_key)
        if brief is not None:
            payload["result"] = ScoutResponse(
                brief=brief,
                duration_seconds=brief.duration_seconds,
                share_key=job.share_key,
            ).model_dump(mode="json")
        else:
            # The run finished but the brief did not survive to the cache.
            payload["status"] = "error"
            payload["error_kind"] = "failed"
            payload["error"] = "The report could not be saved. Please try again."
            monitoring.warn(
                "Scout finished but its brief was not in the cache",
                share_key=job.share_key,
            )

    return JSONResponse(content=payload)


@app.get("/r/{key}")
async def shared_report_page(key: str):
    """Human-facing share URL. Serves the same app shell; the frontend reads
    the key from the path and loads the report."""
    return FileResponse(str(FRONTEND_DIR / "index.html"))


@app.get("/report/{key}.md")
async def report_markdown(key: str):
    brief = cache.get_by_key(key)
    if brief is None:
        raise HTTPException(status_code=404, detail="Report not found or expired")

    name = brief.evidence.company.name.lower().replace(" ", "_")
    return PlainTextResponse(
        content=brief_to_markdown(brief),
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="scout_{name}.md"'
        },
    )


@app.get("/report/{key}.pdf")
async def report_pdf(key: str):
    brief = cache.get_by_key(key)
    if brief is None and store.is_enabled():
        brief = store.load_by_key(key)
    if brief is None:
        raise HTTPException(status_code=404, detail="Report not found or expired")

    html = pdf_export.brief_to_print_html(brief, share_key=key)
    name = brief.evidence.company.name.lower().replace(" ", "_")
    return PlainTextResponse(
        content=html,
        media_type="text/html; charset=utf-8",
        headers={
            "Content-Disposition": f'inline; filename="scout_{name}.html"'
        },
    )


@app.get("/report/{key}")
async def report_json(key: str):
    brief = cache.get_by_key(key)
    if brief is None:
        raise HTTPException(status_code=404, detail="Report not found or expired")

    return JSONResponse(
        content=ScoutResponse(
            brief=brief,
            duration_seconds=brief.duration_seconds,
            share_key=key,
        ).model_dump(mode="json")
    )


@app.post("/outreach/generate")
async def outreach_generate(request: Request):
    """Draft an outreach email from a brief's own evidence.

    No new research runs here — the whole point of generating from an
    existing brief rather than researching again is that the expensive part
    is already paid for and already sitting in the database.
    """
    body = await request.json()
    share_key = body.get("share_key", "")
    person_name = body.get("person_name", "")
    sender_name = body.get("sender_name", "").strip() or "—"

    brief = cache.get_by_key(share_key)
    if brief is None:
        raise HTTPException(status_code=404, detail="Report not found or expired")

    owner = (auth.current_user(request) or {}).get("e")
    result = outreach.draft(brief, person_name, sender_name, share_key, owner=owner)
    return JSONResponse(content=result, status_code=200 if result.get("ok") else 422)


@app.post("/outreach/{draft_id}/send")
async def outreach_send(draft_id: int, request: Request):
    """Send a draft. The found/inferred/candidate rule is checked again here,
    server-side, regardless of what the confirmation dialog on screen showed —
    a client-side-only restriction is not a restriction."""
    body = await request.json()
    result = outreach.send(
        draft_id,
        subject=body.get("subject", ""),
        body_text=body.get("body_text", ""),
        confirmed_inferred=bool(body.get("confirmed_inferred")),
    )
    return JSONResponse(content=result, status_code=200 if result.get("ok") else 422)


@app.get("/notes/{share_key}")
async def get_notes(share_key: str, request: Request):
    user = auth.current_user(request)
    if not user:
        return JSONResponse({"notes": []})
    return JSONResponse({"notes": notes.list_for(share_key)})


@app.post("/notes/{share_key}")
async def add_note(share_key: str, request: Request):
    user = auth.current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Sign in required")
    body = await request.json()
    text = (body.get("body") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Note cannot be empty")
    result = notes.add(share_key, user["e"], text)
    if not result:
        raise HTTPException(status_code=500, detail="Could not save note")
    return JSONResponse(result, status_code=201)


@app.delete("/notes/{note_id}")
async def delete_note(note_id: int, request: Request):
    user = auth.current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Sign in required")
    if notes.delete(note_id, user["e"]):
        return JSONResponse({"ok": True})
    raise HTTPException(status_code=404, detail="Note not found or not yours")


@app.get("/compare")
async def compare_page():
    return FileResponse(str(FRONTEND_DIR / "index.html"))


@app.get("/compare-data")
async def compare_data(a: str = "", b: str = ""):
    """Load two briefs for side-by-side comparison. Zero LLM cost."""
    if not a or not b:
        raise HTTPException(status_code=400, detail="Two share keys required (?a=KEY1&b=KEY2)")
    brief_a = cache.get_by_key(a) or (store.load_by_key(a) if store.is_enabled() else None)
    brief_b = cache.get_by_key(b) or (store.load_by_key(b) if store.is_enabled() else None)
    if not brief_a:
        raise HTTPException(status_code=404, detail=f"Report {a} not found")
    if not brief_b:
        raise HTTPException(status_code=404, detail=f"Report {b} not found")
    return JSONResponse({
        "a": ScoutResponse(brief=brief_a, duration_seconds=brief_a.duration_seconds, share_key=a).model_dump(mode="json"),
        "b": ScoutResponse(brief=brief_b, duration_seconds=brief_b.duration_seconds, share_key=b).model_dump(mode="json"),
    })


@app.get("/recent")
async def recent_scouts():
    """Recently scouted companies, for the home page.

    These are already-paid-for reports, so surfacing them turns a cache hit
    into the obvious next click rather than a lucky coincidence.
    """
    durable = store.recent()
    return JSONResponse(content={"recent": durable or cache.recent()})


def _check_admin(request: Request) -> None:
    """Gate the operational pages behind a single shared token.

    One operator, so accounts and passwords would be machinery without a
    benefit. Accepts the token from a header or a query parameter, the latter
    so the page can be opened from a bookmark. Open when no token is set,
    which is what local development wants.
    """
    expected = settings.admin_token
    if not expected:
        return
    supplied = (
        request.headers.get("x-admin-token")
        or request.query_params.get("key")
        or ""
    )
    # Constant-time compare: a plain != leaks the token a character at a time
    # to anyone willing to measure.
    if not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=404, detail="Not found")


@app.get("/usage")
async def usage_report(request: Request):
    _check_admin(request)
    """What has been spent against each provider's free tier.

    Counted by this process, so a restart loses history and the provider's own
    console remains the authority. Surfaced anyway: an approximate number you
    can see beats an exact one behind three separate logins.
    """
    models = [
        settings.llm_model_resolver,
        settings.llm_model_extractor,
        settings.llm_model_analyst,
        settings.llm_model_scorer,
    ]
    seen: set[str] = set()
    ordered = [m for m in models + settings.fallback_models
               if not (m in seen or seen.add(m))]

    snapshot = usage.snapshot(ordered)
    snapshot["stages"] = {
        "resolver": settings.llm_model_resolver,
        "extractor": settings.llm_model_extractor,
        "analyst": settings.llm_model_analyst,
        "scorer": settings.llm_model_scorer,
    }
    # Ask Hunter directly rather than reporting our own guess. "Key is set"
    # and "key works" are different facts, and only the second one is useful
    # when a lookup silently returns nothing.
    account = hunter.account()
    snapshot["hunter"]["configured"] = account["configured"]
    snapshot["hunter"]["valid"] = account.get("valid")
    snapshot["hunter"]["reason"] = account.get("reason")
    if account.get("valid") and account.get("limit"):
        # Hunter counts searches this process never saw, so prefer its number.
        # Ours is kept alongside rather than overwritten: when the two differ,
        # that difference is the only way to tell "Hunter was never called"
        # from "Hunter was called and their count is stale".
        snapshot["hunter"]["used_here"] = snapshot["hunter"]["used"]
        snapshot["hunter"]["used"] = account["used"]
        snapshot["hunter"]["limit"] = account["limit"]
        snapshot["hunter"]["remaining"] = max(0, account["limit"] - account["used"])
        snapshot["hunter"]["authoritative"] = True

    # What actually happened last time, not just what is configured.
    snapshot["hunter"]["last_lookup"] = hunter.last_lookup()

    snapshot["apollo"]["configured"] = apollo_configured()
    # Tavily's own number, not ours. Ours said 367 used while Tavily said
    # 1,205 against a 1,000 limit — a counter that only ever saw this
    # process's calls, reporting headroom that did not exist.
    tav = tavily_usage.fetch()
    if tav.get("available"):
        snapshot["tavily"]["used"] = tav["used"]
        snapshot["tavily"]["limit"] = tav["limit"]
        snapshot["tavily"]["remaining"] = tav["remaining"]
        snapshot["tavily"]["plan"] = tav.get("plan")
        snapshot["tavily"]["exhausted"] = tav.get("exhausted")
        snapshot["tavily"]["authoritative"] = True

    snapshot["accounts"] = users.summary()
    snapshot["activity"] = store.activity_summary()
    snapshot["mail"] = {"configured": mailer.is_configured()}
    return JSONResponse(content=snapshot)


@app.get("/login")
async def login_page(request: Request):
    # Already signed in, or sign-in is switched off: no reason to show a door
    # that is standing open.
    if auth.is_signed_in(request):
        return RedirectResponse("/", status_code=303)
    return FileResponse(str(FRONTEND_DIR / "login.html"))


@app.post("/login")
async def login_submit(
    request: Request,
    email: str = Form(""),
    password: str = Form(""),
    next: str = Form("/"),
):
    if not auth.authenticate(email, password):
        # One message for both failures. Saying which half was wrong tells an
        # attacker whether the address exists.
        return RedirectResponse("/login?error=1", status_code=303)

    # Only ever redirect within this site; an open redirect turns a login page
    # into a convincing way to send someone somewhere else.
    target = next if next.startswith("/") and not next.startswith("//") else "/"
    response = RedirectResponse(target, status_code=303)
    response.set_cookie(
        auth.COOKIE_NAME,
        auth.issue(email.strip().lower()),
        max_age=auth.SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=True,
    )
    return response


@app.get("/signup")
async def signup_page(request: Request):
    if auth.is_signed_in(request):
        return RedirectResponse("/", status_code=303)
    return FileResponse(str(FRONTEND_DIR / "signup.html"))


@app.post("/signup")
async def signup_submit(
    email: str = Form(""),
    password: str = Form(""),
    next: str = Form("/"),
):
    ok, message = users.create(email, password)
    if not ok:
        return RedirectResponse(f"/signup?error={quote(message)}", status_code=303)

    # Best-effort and off the critical path: a mail provider hiccup must not
    # turn a successful signup into a failed one.
    mailer.send_welcome(users.normalise_email(email))

    # Registering signs you in immediately — a second form to fill in right
    # after the first would be a worse experience than it is worth.
    target = next if next.startswith("/") and not next.startswith("//") else "/"
    response = RedirectResponse(target, status_code=303)
    response.set_cookie(
        auth.COOKIE_NAME,
        auth.issue(users.normalise_email(email)),
        max_age=auth.SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=True,
    )
    return response


_GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
_GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"
_oauth_states: dict[str, tuple[float, str]] = {}


def _google_oauth_enabled() -> bool:
    return bool(settings.google_client_id and settings.google_client_secret)


@app.get("/auth/google")
async def google_login(request: Request):
    if not _google_oauth_enabled():
        print(f"[oauth] Google OAuth not enabled. client_id set: {bool(settings.google_client_id)}, "
              f"client_secret set: {bool(settings.google_client_secret)}", flush=True)
        return RedirectResponse(
            "/login?error=" + quote("Google sign-in is not set up yet."),
            status_code=303,
        )

    state = secrets.token_urlsafe(32)
    next_url = request.query_params.get("next", "/")
    if not next_url.startswith("/") or next_url.startswith("//"):
        next_url = "/"
    _oauth_states[state] = (time.time(), next_url)

    # Housekeeping: drop states older than 10 minutes.
    cutoff = time.time() - 600
    for k in [k for k, (t, _) in _oauth_states.items() if t < cutoff]:
        _oauth_states.pop(k, None)

    scheme = request.headers.get("x-forwarded-proto", "https")
    host = request.headers.get("host", "scout.yeboah.works")
    redirect_uri = f"{scheme}://{host}/auth/google/callback"

    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email",
        "state": state,
        "prompt": "select_account",
    }
    return RedirectResponse(f"{_GOOGLE_AUTH_URL}?{urlencode(params)}", status_code=303)


@app.get("/auth/google/callback")
async def google_callback(request: Request):
    if not _google_oauth_enabled():
        return RedirectResponse(
            "/login?error=" + quote("Google sign-in is not set up yet."),
            status_code=303,
        )

    error = request.query_params.get("error")
    if error:
        return RedirectResponse("/login?error=Google+sign-in+was+cancelled", status_code=303)

    code = request.query_params.get("code", "")
    state = request.query_params.get("state", "")

    stored = _oauth_states.pop(state, None)
    if not stored or time.time() - stored[0] > 600:
        return RedirectResponse("/login?error=Sign-in+expired.+Please+try+again.", status_code=303)

    next_url = stored[1]

    scheme = request.headers.get("x-forwarded-proto", "https")
    host = request.headers.get("host", "scout.yeboah.works")
    redirect_uri = f"{scheme}://{host}/auth/google/callback"

    try:
        async with httpx.AsyncClient() as client:
            token_resp = await client.post(_GOOGLE_TOKEN_URL, data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            })
            if token_resp.status_code != 200:
                print(f"[oauth] Token exchange failed: {token_resp.status_code} {token_resp.text[:300]}", flush=True)
                return RedirectResponse(
                    "/login?error=" + quote("Google sign-in failed. Please try again."),
                    status_code=303,
                )
            tokens = token_resp.json()

            userinfo_resp = await client.get(
                _GOOGLE_USERINFO_URL,
                headers={"Authorization": f"Bearer {tokens['access_token']}"},
            )
            if userinfo_resp.status_code != 200:
                print(f"[oauth] Userinfo failed: {userinfo_resp.status_code}", flush=True)
                return RedirectResponse(
                    "/login?error=" + quote("Could not read your Google account."),
                    status_code=303,
                )
            userinfo = userinfo_resp.json()
    except Exception as exc:
        print(f"[oauth] Exception during Google sign-in: {exc}", flush=True)
        return RedirectResponse(
            "/login?error=" + quote("Google sign-in failed. Please try again."),
            status_code=303,
        )

    email = (userinfo.get("email") or "").strip().lower()
    if not email:
        return RedirectResponse("/login?error=No+email+from+Google", status_code=303)

    ok, msg = users.find_or_create_oauth(email)
    if not ok:
        return RedirectResponse(f"/login?error={quote(msg)}", status_code=303)

    mailer.send_welcome(email)

    target = next_url if next_url.startswith("/") and not next_url.startswith("//") else "/"
    response = RedirectResponse(target, status_code=303)
    response.set_cookie(
        auth.COOKIE_NAME,
        auth.issue(email),
        max_age=auth.SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=True,
    )
    return response


@app.get("/forgot-password")
async def forgot_password_page():
    return FileResponse(str(FRONTEND_DIR / "forgot-password.html"))


@app.post("/forgot-password")
async def forgot_password_submit(request: Request):
    body = await request.json()
    email = (body.get("email") or "").strip().lower()

    if not email:
        return JSONResponse({"ok": False, "message": "Enter your email address."})

    if users.exists(email):
        token = password_reset.issue(email)
        scheme = request.headers.get("x-forwarded-proto", "https")
        host = request.headers.get("host", "scout.yeboah.works")
        reset_url = f"{scheme}://{host}/reset-password?token={token}"
        mailer.send_reset(email, reset_url)

    return JSONResponse({
        "ok": True,
        "message": "If an account with that email exists, a reset link has been sent. Check your inbox.",
    })


@app.get("/reset-password")
async def reset_password_page():
    return FileResponse(str(FRONTEND_DIR / "reset-password.html"))


@app.post("/reset-password")
async def reset_password_submit(request: Request):
    body = await request.json()
    token = body.get("token", "")
    new_password = body.get("password", "")

    email = password_reset.verify(token)
    if not email:
        return JSONResponse({"ok": False, "expired": True,
                             "message": "This reset link has expired or is not valid."})

    ok, message = users.update_password(email, new_password)
    if not ok:
        return JSONResponse({"ok": False, "message": message})

    return JSONResponse({"ok": True})


@app.get("/use-cases")
async def use_cases_page():
    return FileResponse(str(FRONTEND_DIR / "use-cases.html"))


@app.get("/privacy")
async def privacy_page():
    return FileResponse(str(FRONTEND_DIR / "privacy.html"))


@app.get("/terms")
async def terms_page():
    return FileResponse(str(FRONTEND_DIR / "terms.html"))


@app.post("/logout")
async def logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(auth.COOKIE_NAME)
    return response


@app.get("/about")
async def about_page():
    """What the tool does, how to read it, and what it will not tell you.

    Its own page rather than more copy on the home page: someone arriving to
    scout a company wants the search box, and someone deciding whether to
    trust the output wants several hundred words. Those are different visits.
    """
    return FileResponse(str(FRONTEND_DIR / "about.html"))


@app.get("/pipeline-stages")
async def pipeline_stages():
    """The ordered stage names, so the loading screen is never out of sync
    with how many stages the pipeline actually runs.

    Fetched once at page load rather than hardcoded as six <div>s in the
    HTML — the failure this replaces is a Python change to STAGE_LABELS with
    no matching HTML edit, which is exactly the kind of drift that goes
    unnoticed until someone counts checkmarks against a seventh stage that
    never gets a row.
    """
    return JSONResponse(content={"stages": STAGE_LABELS})


@app.get("/capacity")
async def capacity():
    """How many fresh reports are left today. Public, deliberately thin.

    The free tier allows roughly three fresh companies a day across every
    visitor. Saying nothing about that means the fourth person to arrive types
    a company name, waits, and is told the run failed — which reads as a broken
    site rather than a shared budget.

    Only the count and the reset time. Which models are in use, what else is
    configured and how much of each provider is left stay behind the admin
    token; none of that helps a visitor decide whether to search.
    """
    models = [
        settings.llm_model_resolver,
        settings.llm_model_extractor,
        settings.llm_model_analyst,
        settings.llm_model_scorer,
    ]
    seen: set[str] = set()
    ordered = [m for m in models + settings.fallback_models
               if not (m in seen or seen.add(m))]
    snap = usage.snapshot(ordered)
    return JSONResponse(content={
        "scouts_left": snap["gemini"]["approx_scouts_left"],
        "resets_in_seconds": snap["gemini"]["resets_in_seconds"],
    })


@app.get("/usage-page")
async def usage_page():
    # The shell is public; the numbers behind it are not. The page asks for
    # the token and keeps it, so this stays bookmarkable.
    return FileResponse(str(FRONTEND_DIR / "usage.html"))


@app.get("/health")
async def health():
    """Also reports whether error monitoring is live.

    Kept here rather than in a debug route: whether errors are being reported
    is part of whether the service is healthy, and a monitoring outage is
    otherwise invisible by definition.
    """
    return {
        "status": "ok",
        "monitoring": monitoring.is_enabled(),
        "database": db.status(),
        "auth": "enabled" if auth.is_enabled() else "open",
        "google_oauth": "enabled" if _google_oauth_enabled() else "off",
    }
