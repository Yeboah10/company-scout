# Tasks — Company Scout

## Sprint 1 — Research Engine
- [x] Initialize repository and project structure
- [x] Set up Python backend with FastAPI
- [x] Define data models (Company, Source, Claim, Person)
- [x] Implement Tavily search service
- [x] Implement LLM service (Gemini)
- [x] Build company resolver
- [x] Build multi-query searcher
- [x] Build evidence extractor
- [x] Build research pipeline orchestrator
- [x] Add FastAPI endpoint + CLI entry point
- [x] Test with real companies (Spiro, BasiGo)

## Sprint 2 — Analysis Engine
- [x] Implement strategic signal identification
- [x] Implement story angle generation
- [x] Implement case study assessment
- [x] Implement outreach opportunity analysis
- [x] Add analyst to pipeline

## Sprint 3 — Scoring & Report
- [x] Implement four-score opportunity assessment
- [x] Implement overall Scout Score
- [x] Build full Company Intelligence Brief output
- [x] Build source ledger
- [ ] Run 20-company evaluation — blocked, see Quota below

## Sprint 4 — Web Interface
- [x] Build input screen (plain HTML/CSS/JS, not Next.js)
- [x] Build report display with tabs
- [x] Connect to backend API
- [x] Deploy to Render at https://scout.yeboah.works

## Sprint 5 — Performance & Cost
- [x] Cache completed briefs (repeat lookups: ~317s -> 0.04s)
- [x] Parallelise Tavily search queries
- [x] Derive search year from today instead of hardcoding
- [x] Per-visitor rate limiting, generic error responses
- [x] Persist cache in Render Key Value (falls back to disk locally)

## Sprint 6 — Sharing & Export
- [x] Shareable report links at /r/{key}
- [x] Markdown export at /report/{key}.md
- [x] Print/PDF styles (light theme, all tab panels expanded)
- [x] Replace JSON download with Markdown in web UI and CLI
- [x] Cache hits no longer count against the rate limit

## Known constraint — Gemini free tier quota
A full scout costs ~6 Gemini calls (1 resolver + ~3 extractor batches +
1 analyst + 1 scorer). The free tier allows 20 calls/day, so roughly
**3 fresh companies per day**, shared across all visitors.

Two consequences:
- The 20-company evaluation needs ~120 calls (~6 days of free quota).
- Requests-per-minute is also capped. Parallelising LLM calls was tried
  and reverted: it exhausts the minute budget and later pipeline stages
  stall in backoff, making runs slower (317s parallel vs ~255s sequential).

## Remaining from PRD — the real gap
- [ ] Run the 20-company evaluation set (eval/companies.json)
- [ ] Populate eval/failure_log.md with observed failures
- [ ] Make recency actually count in scoring (PRD principle #5 is stated
      in prompts but never weighted)

The evaluation is the largest outstanding item. Until it runs, PRD success
criteria 2, 4, 6 and 9 are unverified — including "can correctly say some
companies aren't worth pursuing", which is the product's core claim.

## Possible next steps (UX)
- [ ] Recent-scouts list on the homepage (cheap now that the cache persists)
- [ ] Sort evidence recent-first and surface dates prominently
- [ ] Show which claims corroborate each other across sources
- [ ] Let the user force a refresh of a cached report
