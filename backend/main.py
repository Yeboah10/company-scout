import asyncio
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import FastAPI, HTTPException
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


@app.get("/")
async def index():
    return FileResponse(str(FRONTEND_DIR / "index.html"))


def _run_research(query: str):
    pipeline = ResearchPipeline()
    return pipeline.research(query)


@app.post("/scout")
async def scout_company(request: ScoutRequest):
    if not request.query.strip():
        raise HTTPException(status_code=400, detail="Company name or URL required")

    try:
        loop = asyncio.get_event_loop()
        brief = await loop.run_in_executor(executor, _run_research, request.query.strip())
        response = ScoutResponse(brief=brief, duration_seconds=brief.duration_seconds)
        return JSONResponse(content=response.model_dump(mode="json"))
    except Exception as e:
        tb = traceback.format_exc()
        print(f"ERROR in /scout: {tb}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health():
    return {"status": "ok"}
