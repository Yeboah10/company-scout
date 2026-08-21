from fastapi import FastAPI, HTTPException

from backend.models.schemas import ScoutRequest, ScoutResponse
from backend.pipeline.researcher import ResearchPipeline

app = FastAPI(
    title="Company Scout",
    description="AI-powered company intelligence and opportunity assessment",
    version="0.2.0",
)


@app.post("/scout", response_model=ScoutResponse)
async def scout_company(request: ScoutRequest):
    if not request.query.strip():
        raise HTTPException(status_code=400, detail="Company name or URL required")

    pipeline = ResearchPipeline()
    brief = pipeline.research(request.query.strip())

    return ScoutResponse(brief=brief, duration_seconds=brief.duration_seconds)


@app.get("/health")
async def health():
    return {"status": "ok"}
