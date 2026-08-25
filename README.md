# Company Scout

**[scout.yeboah.works](https://scout.yeboah.works)** — an evidence-backed research tool for African companies. Enter a name, get a brief that says whether the company is worth your attention, whether you can actually reach anyone there, and what the public record does *not* say.

Built for Africa Business School (UM6P) — a case writer's tool for deciding what to research, who to contact, and what to write about.

## What it does

Type a company name. In a few minutes you get:

- **Two scores, not one** — *worth your attention* and *can you reach them*, kept deliberately separate. A company can be a great story and impossible to contact (a collapsed startup is a case study, not a lead), and one blended number hides exactly that distinction.
- **A signal ledger** — strategic developments the research turned up, each with its evidence, its interpretation, and a question worth asking, ranked by confidence.
- **A coverage report** — which of nine research areas came back with evidence and which came back empty. A gap is a fact about the public record, not a verdict on the company.
- **People, with dates on their roles** — every person carries whether their role is *current* or *former*, and as of when the evidence says so. Nobody who has left gets offered as a contact.
- **Contacts in three honest tiers** — *found* (published, with the page it came from), *inferred* (a guessed address, built from a pattern actually observed at that company), and *candidate* (a generic format, clearly labelled as a guess). Never merged into one list.
- **A source ledger** — every claim traces to a dated, quality-rated source you can open yourself.

Full explanation, with worked examples, at [scout.yeboah.works/about](https://scout.yeboah.works/about).

## Why it's careful about being wrong

This project has a running log of its own failures — [`eval/failure_log.md`](eval/failure_log.md) — because a research tool that occasionally states things confidently and wrongly is worse than one that says "not established." A few examples of what that log tracks:

- A collapsed company once scored *HIGH PRIORITY* because one blended score couldn't express "great story, no way in." Fixed by splitting the score.
- A brief once listed an executive by a role he'd left months earlier, because nothing in the data model recorded *when* a role was true. Fixed by adding tenure to every person.
- An evaluation once reported a 33% accuracy rate that was pure measurement error — the matcher, not the pipeline, was wrong. Replaced with a judge that compares by meaning.

The patterns behind those failures — not just the individual bugs — are written up at the bottom of the failure log.

## Architecture

- **Backend:** Python 3.12, FastAPI
- **Research:** Google Gemini (multi-model routing across the free tier, with Groq and Cerebras as fallbacks when quota runs out), Tavily search (with Exa as a fallback)
- **Storage:** Postgres (durable briefs, accounts) with Redis as a fast-path cache
- **Frontend:** plain HTML/CSS/JS — no framework, no build step
- **Monitoring:** Sentry

See [`ARCHITECTURE.md`](ARCHITECTURE.md) for "I want to change X → open file Y."

## Running it locally

```bash
pip install -r requirements.txt
cp .env.example .env
# edit .env: set GOOGLE_API_KEY (Gemini) and TAVILY_API_KEY
```

**CLI:**
```bash
python -m backend "Spiro"
```

**Web server:**
```bash
uvicorn backend.main:app --reload
# POST {"query": "Spiro"} to http://localhost:8000/scout
```

Sign-in, Postgres, Redis, Sentry, Hunter/Apollo contact enrichment, and the Groq/Cerebras/Exa fallbacks are all optional — the app runs with just the two keys above and degrades cleanly without the rest. See `.env.example` for the full list.

## Project status

The largest open item is the evaluation: `eval/companies.json` defines 24 companies (20 general cases plus 4 regression cases built from real bugs this project shipped) with blind expectations for both scores; 4 have been run in full. Current state, open items, and priority order are tracked in [`BACKLOG.md`](BACKLOG.md). [`UPDATE.md`](UPDATE.md) is a periodic narrative snapshot of what's shipped.

## Constraints this project designs around

Gemini's free tier caps at roughly 20 calls/day *per model*; a scout costs about 6, so the practical limit is a handful of fresh companies a day, shared across every visitor — which is why caching, the fallback chains, and the honest capacity indicator on the homepage all exist. This is a deliberate constraint of building on free infrastructure, not an oversight.
