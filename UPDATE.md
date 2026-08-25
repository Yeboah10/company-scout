# Company Scout — update report

**Live:** https://scout.yeboah.works
**Repo:** github.com/Yeboah10/company-scout
**Covers:** 5 commits since the last report
**Written:** 25 August 2026

This replaces the previous update. The last one covered the accounts system,
Postgres, the Modernist redesign and the Company Workspace, three resilience
fallback chains (Gemini→Groq→Cerebras, Tavily→Exa), the search-budget waste
fix, and the failure log. All of that stands. What follows is everything
since.

---

## 1. Outreach — the first version of Phase 3

The People module (built last report) generates evidence, contacts and
tenure. What was missing was doing anything with it. That gap is closed:
every reachable person on the People tab now has a **Draft outreach** button.

**Generated from evidence already gathered — nothing new is researched.** The
draft is written from the brief's own claims and signals; no extra search
call, no extra extraction pass. One Gemini call, using data already paid for.

**Three contact tiers, three different behaviours, checked twice:**

| Tier | Behaviour |
|---|---|
| **Found** — a confirmed personal address | Sends on one click |
| **Inferred** — a guessed address built from an observed pattern | A confirmation dialog names the risk in plain language before it can send |
| **Candidate** — a generic-format guess, no company-specific evidence | Never offered a draft at all |

The rule is enforced **server-side**, not just in the interface. A request
that skips the confirmation step, or targets a candidate-tier address, is
refused by the backend regardless of what the frontend sent — a restriction
that exists only in the UI is not a restriction.

**A former employee is refused before any AI call runs**, for the same
reason a candidate-tier person is: there is nothing to draft, and checking
that costs nothing, so it happens first rather than after spending quota.

Verified under mock rather than assumed: every refusal path (former
employee, candidate-only contact, no contact at all, an unrecognised
person), every send-tier branch (candidate blocked, inferred blocked without
confirmation, inferred sent once confirmed, found sent without needing
confirmation, an already-sent draft blocked, a nonexistent draft blocked),
and confirmation that only the genuine case reaches the LLM call while both
refusal cases never do.

Drafts and sends are recorded in Postgres — one row per attempt, the same
pattern as every other table in this project.

---

## 2. A usage counter, closing out the original PRD's success criterion #10

criterion #10 was *"actually used instead of manual research."* Until now
that question had no way of being answered — two accounts existed and
nothing recorded whether either had ever run a real scout.

`scout_runs` already logs one row per run, so this reads data that already
existed rather than adding new tracking: total scouts run, how many in the
last 7 days, how many distinct companies. Live reading at the time of
writing: **12 scouts run, 12 in the last 7 days, 11 distinct companies.**

Per-user attribution is scaffolded but not wired — the signed-in session's
email is not yet threaded through to the save path, so the breakdown by
owner returns empty for now. Noted as a follow-up rather than treated as
done.

---

## 3. A real bug, found from a live Sentry error, not by inspection

A scout on "Big Cabal Media" crashed with a bare `ServerError: high demand`.
Investigation traced it to a gap in the LLM retry logic: Google's SDK has two
separate exception classes, `ClientError` (rate limits, quota) and
`ServerError` (Google's own capacity problem). **Only `ClientError` was
handled.** A `ServerError` was retried three times, instantly, on the same
overloaded model, then raised straight to the user as a stack trace.

**Fixed properly, not just caught.** The chain now rotates to a different
model first — a second model being overloaded at the same instant is
unlikely — and only once every model has failed on the same sweep does it
wait and retry the whole chain, backing off further each round.

**The model is never marked as quota-exhausted for this.** High demand is
Google's momentary capacity, not the daily allowance being spent; marking it
exhausted would have corrupted the usage page the same way an earlier Hunter
bug did. This was checked explicitly under test, not assumed.

**The error message is honestly qualified, not just reassuring.** It tells
the user this is temporary and that a retry should be quick — verified
against the actual pipeline code that this is true: the run checkpoints
right before scoring, which is exactly the stage where this failure was
observed, so a retry of the same query costs one call, not the whole
research pass again.

---

## 4. Two small corrections

**The favicon** moved from the original indigo to ABS amber, with corners
squared off to match the Modernist system everywhere else — a UM6P/ABS icon
was still carrying the pre-redesign colour.

**The README was actively wrong, not just thin.** It instructed a new
contributor to set `ANTHROPIC_API_KEY`. The project uses Google Gemini and
always has — confirmed against `.env.example` and the code itself. Anyone
following the README's own setup instructions exactly would have failed at
the first step. It also pointed to `TASKS.md` for current progress, which was
itself marked a historical log pointing back to `BACKLOG.md` in an earlier
commit — a loop leading nowhere. Rewritten to describe what is actually
here, with the failure log linked directly: a tool that shows its own
mistakes in public reads as more credible than one that only lists features.

---

## 5. Domain verification completed

`yeboah.works` is now verified with Resend — DKIM, SPF via a CNAME pair,
DMARC, all added directly at the registrar rather than through a Cloudflare
nameserver migration that was attempted first and abandoned partway through
(the Cloudflare zone has since been removed cleanly). Welcome emails, and now
outreach emails, send from `tebra@yeboah.works` to real inboxes rather than a
sandbox address that only ever reached the account owner.

---

## Where it stands

**Live and working:** outreach with three-tier send safety, the usage
counter, the corrected Gemini retry logic, verified email sending from the
real domain, the corrected README and favicon.

**Confirmed dead, not yet removed:** Hunter.io. The API key is valid, but
every real lookup attempt has been rejected, and Hunter's own account shows
zero successful searches ever recorded. It is not currently doing anything
useful and is flagged for a proper look rather than continued silent
inclusion.

**Structural gap worth flagging:** scout jobs run in a thread pool inside the
same process serving the website. A Render restart mid-scout loses the job
silently — no error, no retry, no record. Not fixed yet; the biggest
reliability gap in the system that isn't a feature gap.

**Unchanged from last report and still the largest open item:** the
evaluation. 16 of 24 companies remain unrun. By explicit decision, further
evaluation work is paused in favour of building outreach — the four
category C results and today's live outreach testing are the evidence base
this decision rests on for now.
