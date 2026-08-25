import hmac
import time
import traceback
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote

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
    auth, db, mailer, monitoring, store, tavily_usage, users,
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
PUBLIC_PREFIXES = ("/static/", "/r/", "/report/")
PUBLIC_PATHS = {
    "/login", "/signup", "/logout", "/health", "/about", "/favicon.ico",
    "/usage", "/usage-page",
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

    return await call_next(request)

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


def _run_job(job_id: str, query: str) -> None:
    """Run a scout to completion, recording progress against the job.

    Runs on a worker thread, so nothing here may raise into the caller: every
    outcome is written back onto the job for the client to poll.
    """
    def progress(stage: int, message: str) -> None:
        jobs.update(job_id, stage=stage, message=message)

    try:
        pipeline = ResearchPipeline()
        pipeline.research(query, progress=progress)
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
    # behaviour we want to encourage.
    cached = cache.get(query)
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

    _check_rate_limit(http_request.client.host if http_request.client else "unknown")

    # A scout takes minutes, and the proxy in front of this app abandons any
    # request left unanswered for ~100 seconds. So hand back a job to poll
    # rather than holding the connection open and losing it.
    job = jobs.create(query, share_key=share_key)
    executor.submit(_run_job, job.id, query)

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
        # Configured and working are different facts, and only the second one
        # predicts whether the next write succeeds.
        "database": db.status(),
        "auth": "enabled" if auth.is_enabled() else "open",
    }
