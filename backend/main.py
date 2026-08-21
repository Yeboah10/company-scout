import asyncio
import time
import traceback
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.models.schemas import ScoutRequest, ScoutResponse
from backend.pipeline.researcher import ResearchPipeline

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


@app.post("/scout")
async def scout_company(request: ScoutRequest, http_request: Request):
    if not request.query.strip():
        raise HTTPException(status_code=400, detail="Company name or URL required")

    _check_rate_limit(http_request.client.host if http_request.client else "unknown")

    try:
        loop = asyncio.get_event_loop()
        brief = await loop.run_in_executor(executor, _run_research, request.query.strip())
        response = ScoutResponse(brief=brief, duration_seconds=brief.duration_seconds)
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


@app.get("/health")
async def health():
    return {"status": "ok"}
