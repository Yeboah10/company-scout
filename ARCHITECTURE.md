# Architecture — Company Scout MVP

## Stack

| Layer    | Technology         | Why                                       |
|----------|--------------------|--------------------------------------------|
| Backend  | Python 3.12 + FastAPI | Good fit for AI/research pipelines       |
| LLM      | Claude API (Anthropic) | Structured outputs, strong extraction    |
| Search   | Tavily API         | Built for AI research, returns clean URLs  |
| Database | SQLite (Sprint 1-3) | Zero config, upgrade to Postgres later   |
| Frontend | None yet           | CLI + API first, Next.js after pipeline works |

## Pipeline Architecture

```
User Input (company name or URL)
        │
        ▼
   ┌─────────────┐
   │  Resolver    │  → Identify company, find official website
   └──────┬──────┘
          ▼
   ┌─────────────┐
   │  Searcher    │  → Run multiple search queries (info, news, funding, people)
   └──────┬──────┘
          ▼
   ┌─────────────┐
   │  Extractor   │  → LLM extracts structured claims from search results
   └──────┬──────┘
          ▼
   ┌─────────────┐
   │  Analyst     │  → LLM interprets evidence into signals, scores, angles
   └──────┬──────┘
          ▼
   Structured Company Intelligence Brief
```

## Sprint Plan

### Sprint 1 — Research Engine (current)
`research_company("Spiro")` → structured evidence table

### Sprint 2 — Analysis Engine
`analyse_company(evidence)` → signals, interpretations, questions

### Sprint 3 — Scoring & Report
`score_company(analysis)` → scores, recommendation, full brief

### Sprint 4 — Web Interface
Next.js frontend consuming the API

## Project Structure

```
company-scout/
├── backend/
│   ├── __init__.py
│   ├── main.py            # FastAPI app
│   ├── cli.py             # CLI entry point
│   ├── config.py          # Settings from env vars
│   ├── models/
│   │   ├── __init__.py
│   │   └── schemas.py     # Pydantic models
│   ├── pipeline/
│   │   ├── __init__.py
│   │   ├── resolver.py    # Company identity resolution
│   │   ├── searcher.py    # Multi-query web search
│   │   ├── extractor.py   # LLM-powered evidence extraction
│   │   └── researcher.py  # Orchestrator
│   └── services/
│       ├── __init__.py
│       ├── llm.py         # Claude API wrapper
│       └── search.py      # Tavily API wrapper
├── tests/
├── .env.example
├── .gitignore
├── requirements.txt
├── PRD.md
├── ARCHITECTURE.md
└── TASKS.md
```
