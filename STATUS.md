# Company Scout — Status Report

**Live:** https://scout.yeboah.works
**Repo:** github.com/Yeboah10/company-scout
**Date:** 23 August 2026

---

## What it is

A research tool that takes a company name and produces an evidence-backed
intelligence brief answering one question: **is this company worth my time?**
Focused on African companies. Every claim traces to a dated source, and the
tool is designed to be capable of saying "no".

**Stack:** Python 3.12 · FastAPI · Google Gemini (free tier) · Tavily search ·
plain HTML/CSS/JS frontend · hosted on Render · Redis (Render Key Value) for
caching · Sentry for error reporting.

---

## Pipeline

Six stages. Only four cost LLM calls, which matters because the free tier is
the binding constraint on everything.

| # | Stage | Does | LLM calls |
|---|---|---|---|
| 1 | Resolver | "BasiGo" → which company is that | 1 |
| 2 | Searcher | Builds and runs search queries | 0 |
| 3 | Extractor | Pages → structured claims and people | ~3 |
| 4 | Analyst | Evidence → signals, angles, opportunities | 1 |
| 5 | Scorer | Four dimension scores + recency weighting | 1 |
| 6 | Prospector | Emails and LinkedIn profiles | 0 |

A full scout takes roughly 150–250 seconds and about 6 Gemini calls.

---

## Scoring

Four dimensions, each 0–10 with written reasoning: **story**, **case study**,
**outreach**, **research**. The overall score is their average, adjusted by a
recency factor (0.70–1.05) derived from the actual dates in the evidence.

Two design decisions worth noting:

**Recency adjusts the overall score, not the four dimensions.** Each dimension
carries the model's own reasoning; silently moving a number away from the
sentence explaining it would read as a bug.

**A claim's event date beats its article's publication date.** An article
published this week about a 2019 funding round is old news. Tested: such a
brief correctly drops from 7.0 to 4.9.

Bands: ≥8 HIGH PRIORITY · ≥6 WORTH A LOOK · ≥4 LOW PRIORITY · <4 SKIP

---

## Features

**Research and reporting**
- Background jobs with real stage-by-stage progress (not a timer)
- Shareable links at `/r/{key}`, Markdown export, print/PDF
- Persistent cache — repeat lookups return in ~0.4s and cost no quota
- Recently-scouted list on the home page
- Evidence sorted newest-first; per-claim copy button

**Contacts (Prospector)**
Three tiers, each labelled with what it rests on:
1. **Found** — published somewhere, with the source page recorded
2. **Inferred** — built from a format actually observed at that company
3. **Candidate** — built from formats companies commonly use

Only company-domain addresses are kept, so a journalist's byline on a funding
story is discarded. LinkedIn profiles are collected as URLs only (pages are
never fetched); when a profile isn't found the report says so and links to a
manual search.

**Interface**
Light/dark themes following system preference · mobile layout · changelog
panel · loading skeleton · link previews · usage dashboard at `/usage-page`

**Operations**
- Multi-model routing across four Gemini models (see below)
- Usage tracking per provider, persisted across restarts
- Sentry error reporting, wired to silent-failure paths specifically
- Keep-alive workflow preventing Render cold starts (06:00–23:00 UTC)

---

## The quota constraint, and how it's handled

Gemini's free tier allows **20 requests per day, per model** — the limit is
per model, which the error body confirms
(`GenerateRequestsPerDayPerProjectPerModel-FreeTier`).

The pipeline exploits this. Each stage names a preferred model and falls
through a chain when one is spent:

| Stage | Model |
|---|---|
| Resolver | `gemini-3.1-flash-lite` |
| Extractor | `gemini-3.5-flash-lite` |
| Analyst | `gemini-3.6-flash` |
| Scorer | `gemini-3.5-flash` |

Judgment stages get the stronger models; mechanical ones get lite. Observed
working in production: a run switched from `3.6-flash` to `3.5-flash`
mid-pipeline and completed, at the exact point an earlier run had died.

**Also mitigating quota:**
- Research is checkpointed before scoring, so a run that dies at the last
  stage resumes for 1 call instead of 6 (verified in use)
- Daily-quota errors fail immediately rather than retrying for six minutes
- Cache hits cost nothing and bypass rate limiting

---

## Evaluation

A 20-company set across five categories. Category C is the critical one:
companies that *should* score low, testing the product's core claim.

| Company | Expected | Result | |
|---|---|---|---|
| Pula | 4–6 | **5.7** LOW PRIORITY | ✅ |
| 54gene | 3–5 | **8.0** HIGH PRIORITY | ❌ |
| Twiga Foods | 3–5 | in progress | |
| Kuda Bank | 4–6 | not run | |

**Pula passing** is the first hard evidence the tool can decline to recommend
a real company.

**54gene failing** produced the most useful finding so far. The research was
correct — extraction found the 2023 shutdown, the CEO's resignation and a court
injunction, and the summary said the company collapsed. The scorer read all of
that and rated outreach 6.5, reasoning the founder's legal battles made contact
timely.

Half right, which is what makes it interesting: a collapsed company genuinely
is a strong story, case study and research subject. But there is nobody left to
email. Fixed by tracking `operational_status` and capping outreach
deterministically when a company is defunct — deterministically because the
model had every fact and reasoned past them.

**Known weakness:** findings hit rate is ~33%. Pula missed "parametric
insurance" and "satellite data", its two defining features. Scoring is sound;
the evidence beneath it is thinner than it should be. Under investigation.

---

## Source quality

Press-release wires were dominating results. Three causes: search was steered
by nothing so SEO-heavy syndication won; wires were graded on domain reputation
like any publisher; and the trusted list predated most African tech press.

Now: wires, scraper directories and social profiles are excluded at the search
level, search runs at advanced depth, and two passes go directly at outlets
covering these markets (TechCabal, Technext, Condia, Techpoint, Disrupt Africa,
Ventureburn and others). A wire is graded tier 3 regardless of domain.

**Measured on Moniepoint:** 0 wire results, 10 of 32 sources from independent
African tech press. The same query previously returned Facebook and Instagram.

---

## Architecture

Documented in `ARCHITECTURE.md` as a table mapping "I want to change X" to the
one file that owns it.

```
backend/pipeline/    one file per stage; researcher.py owns the order
backend/services/    llm, search, sources, cache, jobs, recency,
                     contacts, hunter, apollo, usage, monitoring, report
backend/models/      schemas.py — all data shapes
frontend/js/         core, theme, changelog, report, contacts, scout, usage
```

Rules that are easy to violate, so they're written down: new fields start in
`schemas.py`; stage count lives in three places that drift silently; every
fallback must announce itself; found and inferred emails stay in separate
lists so no renderer can present a guess as a fact.

---

## Open items

**Blocked on external parties**
- Hunter.io free-plan verification pending support review
- Apollo free plan excludes the enrichment API entirely (paid only)
- Consequence: email discovery relies on published addresses and common-format
  candidates. LinkedIn works regardless.

**Next**
1. Finish category C (Twiga, Kuda), then categories A, B, D, E — 16 companies
2. Investigate the 33% findings hit rate
3. Discovery feature — "show me interesting climate tech companies" — designed
   but unbuilt; needs a database (Neon free tier recommended over the expiring
   Render Postgres)
4. Outreach drafting, deliberately held until the evaluation passes

**Known limitations**
- Render free Key Value does not persist to disk; cached reports are lost if
  that instance restarts (costs quota to rebuild, not correctness)
- Usage counts only include calls made by the deployed app
- Candidate email addresses are unverified by design; no free way to confirm
  an address exists without SMTP probing, which risks domain blacklisting

---

## Timeline

25 commits. Highlights, most recent first:

- Candidate addresses when nothing can be found
- Apollo as a second email provider (dormant — free plan excludes the API)
- Usage counters persisted across restarts
- Sentry wired to silent-failure paths
- Defunct companies cannot be outreach targets
- Multi-model routing and the usage page
- Frontend split into modules; `ARCHITECTURE.md`
- Contact discovery; source-quality overhaul
- Research checkpointing before scoring
- Recent scouts, sorted evidence, mobile, link previews
- Light/dark mode, changelog, landing page
- Recency made to count in scoring
- Evaluation runner made safe across a multi-day quota budget
- Background jobs (fixed every fresh scout timing out)
- Redis connection verified rather than assumed
