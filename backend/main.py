import time
import traceback
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from backend.models.schemas import ScoutRequest, ScoutResponse
from backend.pipeline.researcher import InsufficientEvidenceError, ResearchPipeline
from backend.services.cache import BriefCache
from backend.services.jobs import TOTAL_STAGES, JobStore
from backend.services.llm import QuotaExhaustedError
from backend.services.report import brief_to_markdown

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

app = FastAPI(
    title="Company Scout",
    description="AI-powered company intelligence and opportunity assessment",
    version="0.3.0",
)

app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

executor = ThreadPoolExecutor(max_workers=2)

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
    except Exception:
        print(f"ERROR in scout job: {traceback.format_exc()}", flush=True)
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
    return JSONResponse(content={"recent": cache.recent()})


@app.get("/health")
async def health():
    return {"status": "ok"}
