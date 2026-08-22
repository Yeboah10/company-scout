# Architecture — where to change what

A map, so a change goes straight to one file instead of a search through the
whole codebase. **If you want to change X, open Y.**

---

## "I want to change…"

| What you want to change | File |
|---|---|
| Which websites are trusted, blocked, or preferred | `backend/services/sources.py` |
| What gets searched for | `backend/pipeline/searcher.py` |
| How a company name is resolved to a real company | `backend/pipeline/resolver.py` |
| What facts get pulled out of pages | `backend/pipeline/extractor.py` |
| Signals, story angles, case-study and outreach analysis | `backend/pipeline/analyst.py` |
| How the four scores are decided | `backend/pipeline/scorer.py` |
| How evidence age changes the score | `backend/services/recency.py` |
| Email and LinkedIn discovery | `backend/pipeline/prospector.py` |
| Email pattern logic and what counts as a valid address | `backend/services/contacts.py` |
| Hunter.io lookups | `backend/services/hunter.py` |
| The order the pipeline runs in | `backend/pipeline/researcher.py` |
| Which model is used, retries, quota errors | `backend/services/llm.py` |
| Caching, share keys, recent-scouts list | `backend/services/cache.py` |
| API endpoints, rate limiting | `backend/main.py` |
| Background jobs and progress | `backend/services/jobs.py` |
| The Markdown export | `backend/services/report.py` |
| Data shapes (any new field goes here first) | `backend/models/schemas.py` |
| Page layout and text | `frontend/index.html` |
| Colours, spacing, light/dark palettes, mobile | `frontend/styles.css` |
| The version history panel's content | `frontend/js/changelog-data.js` |
| Command-line usage | `backend/cli.py` |
| The evaluation harness | `eval/run_eval.py` |

---

## Backend

### `backend/pipeline/` — the stages, in order

Each file is one stage and knows nothing about the others. `researcher.py` is
the only file that knows the order.

1. `resolver.py` — "BasiGo" → which company is that? *(1 LLM call)*
2. `searcher.py` — builds the search queries *(no LLM)*
3. `extractor.py` — pages → claims and people *(~3 LLM calls)*
4. `analyst.py` — evidence → signals, angles, opportunities *(1 LLM call)*
5. `scorer.py` — evidence + analysis → four scores *(1 LLM call)*
6. `prospector.py` — emails and LinkedIn *(no LLM, search only)*

`researcher.py` runs them, checkpoints before scoring, and handles the cache.

### `backend/services/` — capabilities the stages use

| File | Responsibility |
|---|---|
| `llm.py` | Gemini calls, retries, `QuotaExhaustedError` |
| `search.py` | Tavily calls, domain filtering, page fetching |
| `sources.py` | Which domains are trusted, blocked, or preferred |
| `cache.py` | Briefs, checkpoints, share keys, recent list |
| `jobs.py` | Background job state for polling |
| `recency.py` | Evidence dates → a score multiplier |
| `contacts.py` | Address parsing, pattern detection, inference |
| `hunter.py` | Optional Hunter.io enrichment |
| `report.py` | Brief → Markdown |

---

## Frontend

Plain scripts, no build step. **Load order matters** and is set in
`index.html`: `core` first, `scout` last.

| File | Responsibility |
|---|---|
| `js/core.js` | Shared state and helpers everything else uses |
| `js/theme.js` | Light/dark switching |
| `js/changelog-data.js` | The version history content — edit this on release |
| `js/changelog.js` | The panel that displays it |
| `js/report.js` | Rendering a brief into the results view |
| `js/contacts.js` | The Contacts tab |
| `js/scout.js` | The search form, polling, share links, start-up |

---

## Rules worth keeping

**A new field starts in `schemas.py`.** Backend and frontend both read from
there; adding it anywhere else first means adding it twice.

**Stage count lives in three places.** Adding a pipeline stage means updating
`TOTAL_STAGES` in `jobs.py`, the `steps` array in `js/scout.js`, and the step
list in `index.html`. They drift silently otherwise.

**Every fallback announces itself.** A path that quietly degrades is
indistinguishable from one that works — this cost a day when a missing
`REDIS_URL` looked exactly like a working cache.

**Count LLM calls before adding them.** The free tier is ~20/day and it is
per-model, so a scout costs about a third of the daily budget. `prospector.py`
deliberately uses no LLM at all.

**Never present a guess as a fact.** Found and inferred emails are separate
lists in `schemas.py`, not one list with a flag, so no renderer can conflate
them by forgetting to check.
