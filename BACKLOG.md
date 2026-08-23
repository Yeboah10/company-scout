# Company Scout — backlog

Everything outstanding, as numbered items. Say "do 1, 4 and 7" or "do all of
group A" and it gets done in one go.

Ordered by what actually blocks something, not by effort.

---

## Group A — Correctness (the tool is currently wrong about something)

**A1. People have no tenure.**
`Person` carries no date and no current/former status, so someone quoted in an
old article reads identically to someone appointed last month. This is how a
Spiro brief listed Jules Samain as co-CEO after he had moved to Acumen.
*Fix:* add `status` (current / former / unclear) and an as-of date to `Person`;
teach the extractor to mark a role historical when the source is old or the
phrasing is past-tense; show it in the report.
*Touches:* `schemas.py`, `pipeline/extractor.py`, `services/report.py`, `js/report.js`
*Why it matters:* it is the one defect that has actually misled a reader.

**A2. The same company gets several cache entries.**
"Spiro" and "Spiro electric mobility Africa" resolve to the same company but
get separate share keys, so two Spiro reports sit in "Recently scouted" looking
equally current — which is how the stale one got read.
*Fix:* key the cache on the *resolved* company identity, not the raw query;
dedupe the recent list, newest wins.
*Touches:* `services/cache.py`, `pipeline/researcher.py`

**A3. "How the product works" returned 5 results and 0 claims.**
Coverage caught it on Spiro. Unknown whether the search returns the wrong
pages or the extractor discards technical detail as unquotable.
*Fix:* investigate first, then fix whichever it turns out to be. No code
change until the cause is known.

**A4. Verify the four contact fixes on a live run.**
LinkedIn discovery, role-inbox classification, the junk-address filter and
format-from-shape are all verified only in unit tests. Costs one scout.
*Note:* re-running Spiro is the cleanest comparison, since we have a before.

**A5. Confirm Hunter is actually being called.**
The usage page previously masked our own count with Hunter's, so "never
called" and "called, their count is stale" looked identical. Reporting is
fixed; the confirmation still needs a live run. Folds into A4.

---

## Group B — Before you share the link publicly

**B1. Show remaining capacity before someone searches.**
~3 fresh scouts per day, shared across all visitors, and the site never
mentions it. A quiet line under the search box: *"3 fresh reports left today —
saved reports are always free."*

**B2. A real out-of-quota state instead of a raw exception.**
Visitor 4 currently gets `str(e)` from the quota exception, which reads like a
traceback. Should explain plainly, say when it resets, and point at the
recent-scouts list, which costs nothing to serve.
*Touches:* `js/scout.js`, `main.py`

**B3. Decide what happens when two people scout at once.**
Two concurrent runs share a 2-worker thread pool and one quota. Currently
untested under any concurrency at all.

---

## Group C — Evaluation

**C1. Run the remaining 16 companies.**
~96 Gemini calls ≈ 5 days of free quota. Now meaningful, since the
expectations are rewritten as two ranges. Do it on quiet days — it consumes
the same quota visitors need.

**C2. Populate `eval/failure_log.md`.**
Still largely a template. It is meant to record observed failures, and this
session alone produced six worth recording.

**C3. Decide whether to re-run category C under the new expectations.**
Optional. The four results stand; only the expectations changed. Costs 24
calls to redo, and would replace post-hoc expectations with blind ones for a
category we have already reasoned through.

---

## Group D — Engineering hygiene

**D1. One canonical stage definition.**
`TOTAL_STAGES = 6` in `services/jobs.py` and six hardcoded `<div id="step-N">`
in `index.html`. Add a stage and the progress bar silently lies.

**D2. Audit mode.**
A developer view of intermediate pipeline state. When a brief looks wrong the
only recourse today is Render logs.

**D3. `TASKS.md` is stale.**
Lists shipped work as pending. Either update it or fold it into this file.

**D4. `max_results or settings.max_search_results` in `search.py:22`.**
Same `or`-vs-`None` class as the two bugs already fixed. Nobody passes 0
today, so it is latent rather than live — worth closing while the pattern is
fresh.

---

## Group E — Deliberately deferred

**E1. Outreach agent.** Held until the evaluation is trustworthy.
**E2. Discovery feature** ("interesting companies in climate tech"). Last by
agreement.
**E3. Apollo.** Dead end — their person-lookup endpoints are paid-only
regardless of key. The integration exists and stays dormant.

---

## Recommended order

1. **A4 + A5** — one scout, confirms four fixes and answers the Hunter question
2. **A1** — the defect that actually misled you
3. **A2** — stops stale reports being presented as current
4. **B1 + B2** — before the link goes anywhere
5. **A3** — investigate the coverage gap
6. **C1** — the eval, on quiet days
7. Everything else
