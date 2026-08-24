# Company Scout — backlog

Everything outstanding, as numbered items. Say "do 1, 4 and 7" or "do all of
group A" and it gets done in one go.

Ordered by what actually blocks something, not by effort.

---

## Group A — Correctness (the tool is currently wrong about something)

**A1. ~~People have no tenure.~~ Done.**
`Person.status` (current/former/unclear), `role_start`, `role_end`, `as_of`
and a plain-English `tenure_note` are live. The extractor is asked what a
source establishes and as of when, not whether someone "is" the CEO, and
defaults to unclear rather than current on anything it cannot parse. A
departed person now gets no inferred email at all, and the brief says why by
name — the actual harm this defect caused, closed at the root rather than
just labelled.

**A2. The same company gets several cache entries — partially done.**
The *symptom* is fixed: `store.recent()` selects `DISTINCT ON (company_id)`
from Postgres, so "Recently scouted" now shows one Spiro, newest run. The
underlying cause is not: Redis still keys briefs on the raw query string, so
"Spiro" and "Spiro electric mobility Africa" still create two separate cache
entries and two separate share links behind the scenes. Only the list
visitors actually see was fixed.

**A3. "How the product works" returned 5 results and 0 claims.**
Coverage caught it on Spiro. Unknown whether the search returns the wrong
pages or the extractor discards technical detail as unquotable.
*Fix:* investigate first, then fix whichever it turns out to be. No code
change until the cause is known.

**A4. ~~Verify the four contact fixes on a live run.~~ Done.**
Re-ran Spiro live. Role-inbox classification, the junk-address filter and
format-from-shape all confirmed correct. LinkedIn found the company page (a
regression from before) but still 0 of 6 person profiles — a second, deeper
bug, not yet fixed.

**A5. ~~Confirm Hunter is actually being called.~~ Done, and it wasn't.**
The live run showed 3 calls on our own counter against 0 on Hunter's — the
new format-from-shape fix (A1) was itself tripping the "Hunter is redundant"
gate, since it sets `report.pattern` the same as a confirmed one. Fixed to
gate on `pattern_confirmed` instead. Every lookup now records its outcome so
this class of silent mismatch is visible next time, not rediscovered by
accident.

---

## Group B — Before you share the link publicly

**B1. ~~Show remaining capacity before someone searches.~~ Done.**
Public `/capacity` endpoint, deliberately thin — only the count and reset
time, nothing that identifies models or providers. Shown under the search box.

**B2. ~~A real out-of-quota state instead of a raw exception.~~ Done.**
`error_kind === 'quota_exhausted'` now routes to its own explanation instead
of the server's raw message, and points at the saved reports below it.

**B3. Decide what happens when two people scout at once.**
Two concurrent runs share a 2-worker thread pool and one quota. Currently
untested under any concurrency at all.

---

## Group C — Evaluation

**C1. Run the remaining 16 companies.**
~96 Gemini calls ≈ 5 days of free quota. Now meaningful, since the
expectations are rewritten as two ranges. Do it on quiet days — it consumes
the same quota visitors need.

**C2. ~~Populate `eval/failure_log.md`.~~ Done.**
15 real failures logged with root causes, plus the five patterns behind them —
`or` where `None` was meant (4 occurrences), our count versus the provider's
(3), a schema missing a dimension the domain has (2), and precise numbers with
nothing behind them (2). The patterns are the useful part.

**C3. Decide whether to re-run category C under the new expectations.**
Optional. The four results stand; only the expectations changed. Costs 24
calls to redo, and would replace post-hoc expectations with blind ones for a
category we have already reasoned through.

---

## Group D — Engineering hygiene

**D1. ~~One canonical stage definition.~~ Done.**
`STAGE_LABELS` in `services/jobs.py` is now the only place the six stages are
named; `TOTAL_STAGES` is derived from its length rather than typed a second
time. `GET /pipeline-stages` serves the list, and `index.html` builds its
loading rows from it at load rather than hardcoding six `<div>`s — adding a
stage is one line in Python now, not a Python edit plus an HTML edit someone
has to remember to make.

**D2. Audit mode.**
A developer view of intermediate pipeline state. When a brief looks wrong the
only recourse today is Render logs.

**D3. ~~`TASKS.md` is stale.~~ Done.**
Marked as a historical log frozen at Sprint 8, pointing here for anything
current, rather than kept in sync with two todo lists forever.

**D4. ~~`max_results or settings.max_search_results` in `search.py`.~~ Done.**
Same `or`-vs-`None` class as the two bugs already fixed. Nobody was passing
0 today, so it was latent rather than live — closed while the pattern was
fresh.

---

## Group E — Deliberately deferred

**E1. Outreach agent.** Held until the evaluation is trustworthy.
**E2. Discovery feature** ("interesting companies in climate tech"). Last by
agreement.
**E3. Apollo.** Dead end — their person-lookup endpoints are paid-only
regardless of key. The integration exists and stays dormant.

---

## Group F — New since the redesign (accounts, mail, database)

**F1. ~~LinkedIn person-profile discovery is still broken.~~ Closed — unfixable.**
Diagnosed: LinkedIn blocks the crawling that would put profile URLs into a
search index, so no number of searches can find them. The 12 searches per
scout being spent on this were 41% of the entire search budget and returned
zero. Removed; the search link they fell back to is now built directly.
29 searches per scout became 17.

**F5. Exa key not being picked up.**
`EXA_API_KEY` is set in Render but `/usage` reports `configured: false` —
likely a variable-name mismatch. Blocks the search fallback, and therefore
blocks scouting entirely while Tavily is exhausted.

**F6. Verify the coverage fixes on a live run.**
Industry disambiguation (#3) and snippet cleaning (#4) are both fixed and
unverified against a real scout. Blocked on F5 or the Tavily reset. Spiro is
the clean comparison — two prior runs exist.

**F2. `mail_from` needs to move off the Resend sandbox address.**
Currently `onboarding@resend.dev`, which only delivers to the Resend
account's own inbox. Once `yeboah.works` is verified with Resend, change to
`tebra@yeboah.works` — a one-line config change, no new setup.

**F3. A real email sequence, not just a welcome email.**
What exists today is one email sent at signup. A drip sequence (day-3 tip,
week-1 nudge) needs something that fires independent of a visitor being on
the site — a scheduler, which does not exist yet. Real infrastructure, not
a small add.

**F4. Redis cache key duplication (the root cause behind A2).**
Briefs are keyed on the raw query string, not the resolved company. Fixing
this at the source — rather than papering over it in the Postgres read path,
which is what A2 currently does — means resolving the company first and
keying the cache on that.

---

## Recommended order

1. **F5** — fix the Exa key name. Nothing else can run while Tavily is
   exhausted and the fallback is inert.
2. **F6** — one scout to verify the coverage fixes, once F5 unblocks it
3. **C1** — the remaining 16 evaluation companies
4. **F2** — flip the sender address once `yeboah.works` verifies with Resend
5. **F4** — close the cache-duplication root cause properly
6. **D2** — audit mode
7. Everything else
