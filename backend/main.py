import asyncio
import time
import traceback
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from backend.models.schemas import ScoutRequest, ScoutResponse
from backend.pipeline.researcher import ResearchPipeline
from backend.services.cache import BriefCache
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


def _run_research(query: str):
    pipeline = ResearchPipeline()
    return pipeline.research(query)


cache = BriefCache()


@app.post("/scout")
async def scout_company(request: ScoutRequest, http_request: Request):
    query = request.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Company name or URL required")

    # Serve cache hits before rate limiting: they cost no API quota, so there
    # is nothing to protect against, and counting them would punish the exact
    # behaviour we want to encourage.
    cached = cache.get(query)
    if cached is not None:
        return JSONResponse(
            content=ScoutResponse(
                brief=cached,
                duration_seconds=cached.duration_seconds,
                share_key=cache.key_for(query),
            ).model_dump(mode="json")
        )

    _check_rate_limit(http_request.client.host if http_request.client else "unknown")

    try:
        loop = asyncio.get_event_loop()
        brief = await loop.run_in_executor(executor, _run_research, query)
        response = ScoutResponse(
            brief=brief,
            duration_seconds=brief.duration_seconds,
            share_key=cache.key_for(query),
        )
        return JSONResponse(content=response.model_dump(mode="json"))
    except HTTPException:
        raise
    except Exception:
        tb = traceback.format_exc()
        print(f"ERROR in /scout: {tb}")
        raise HTTPException(
            status_code=500,
            detail="Something went wrong while researching this company. Please try again.",
        )


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


@app.get("/health")
async def health():
    return {"status": "ok"}
