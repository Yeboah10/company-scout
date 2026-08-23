# Company Scout — update since the last status report

**Live:** https://scout.yeboah.works
**Repo:** github.com/Yeboah10/company-scout
**Covers:** everything after `STATUS.md` (23 August 2026), eight commits

This is a delta, not a replacement. `STATUS.md` still describes what the tool
is, the stack, and the architecture; nothing there has been invalidated.

---

## 1. One score became two

**The problem.** The tool produced a single 0–10 "Scout Score" that tried to
answer two questions at once: *is this company interesting?* and *can I
actually reach anyone there?* Those questions pull in opposite directions.
54gene — an African genomics startup that collapsed, with a CEO resignation
and a court injunction — is a genuinely good story and an impossible contact.
A blended number has to lie about one of them.

**The fix.** `CompanyBrief` now exposes two computed scores and a verdict:

- `interest_score` — worth your attention (story, case study, research value)
- `reachability_score` — can you get to a person, and are they still trading
- `verdict` — e.g. `PURSUE`, `WORTH WRITING ABOUT — NO WAY IN`

Reachability is deterministic rather than model-judged. It is zeroed outright
when `operational_status` is `defunct` or `winding_down`, then scaled by the
best contact route found: a named person's published address counts fully, a
role inbox 0.8, a LinkedIn profile 0.6, an inferred address 0.4, nothing 0.15.

**Why it matters.** 54gene now reads 8.5 attention / 1.0 reach, which is the
answer a human would give.

---

## 2. Contact discovery is real, with the guesswork labelled

Three tiers, and the distinction is enforced in the schema rather than in
prose:

| Tier | Meaning |
|---|---|
| **Found** | Published somewhere public, with the page that published it recorded |
| **Inferred** | Built from an address format actually observed at this company |
| **Candidate** | The formats companies generally use, applied to known names — explicitly not derived from this company |

Emails are only kept if they are on the company's own domain, which is what
stops a journalist's byline or a PR agency's address being reported as a route
in. LinkedIn profiles are collected as URLs from search results and never
fetched — the pages sit behind a login, and the point is a link to click. When
no profile is found the brief says so plainly and offers a search URL, so the
reader knows whether to look manually or give up.

**Hunter.io is now live** (key verified against their account endpoint). It is
deliberately *not* called on every run: a confirmed address format makes it
redundant, so it is held back for runs that came up short.

**A bug this caught.** Kuda's `dpo@` and `fraud@` were being classified as a
named person's addresses, which inflated how reachable the company looked. The
role-inbox list now covers compliance, legal, security and finance.

**A second one.** The free allowance was hardcoded at 25/month from Hunter's
pricing page. The first time the account was actually queried it reported 50.
The budget guard now takes Hunter's own number, with ours only as a fallback.

---

## 3. The brief now reports what it failed to find

The searcher has asked nine deliberate questions for a while — what they do,
how the product works, how they make money, funding, customers, geography,
people, recent news, and one explicitly adversarial query about layoffs and
shutdowns. Nothing measured whether any of them were answered.

Every search is now tagged with the area that asked for it. An area counts as
covered when a page that search surfaced went on to produce a claim the
extractor kept. That is a weaker statement than "the question was answered" —
it is "the search found something worth extracting" — but it is true, it costs
zero LLM calls, and it cannot drift the way a keyword list would.

A brief now says *"nothing was found on how they make money"* instead of
leaving the reader to notice an absence. It appears in the web report, the
markdown export, and every evaluation result.

The nine areas moved to `backend/services/coverage.py`, next to the code that
reports on them — a question the search stops asking and a gap the brief stops
reporting are the same edit.

---

## 4. Source quality: African tech press over press-release wires

Syndicated press releases were outranking the outlets that actually cover
these markets. Three changes:

- Wire services and low-value aggregators are excluded at the search API
  rather than filtered afterwards, so they no longer consume the results budget
- Two search passes are restricted to African tech press (TechCabal, Technext,
  Condia, TechPoint and others) rather than hoping they rank
- Tier-1 signals are path-anchored after `impact-investor.com` was graded
  tier 1 on a bare "investor" substring

Measured on Moniepoint: zero wire results, 10 of 32 sources from African tech
press. Kuda's run returned 46 sources, up from ~35 before these changes.

---

## 5. The evaluation's headline metric was measuring almost nothing

This is the most important correction in this report, because it means two
previously reported figures were wrong.

The findings matcher required *every* word of an expected finding to appear,
so "shutdown or major restructuring" failed unless the brief contained the
word "or". My first fix over-corrected — "insurance" matched "parametric
insurance" — so it was replaced with an LLM judge that compares by meaning.

Reported rates of 33% and 25% were artefacts. Real rates: Pula 2/3, Twiga 4/4.
Re-checked across all four category C companies afterwards, **all 13 expected
findings are present**. The research half of the tool works; the measurement
of it did not.

---

## 6. Category C was evaluated, and the expectations were wrong — not the tool

Four companies chosen because the tool was *expected* to be unenthusiastic:

| Company | Attention | Reach | Verdict | Old expectation |
|---|---|---|---|---|
| Pula | 6.1 | 6.5 | PURSUE | 4–6 |
| 54gene | 8.5 | 1.0 | WORTH WRITING — NO WAY IN | 3–5 |
| Twiga Foods | 7.2 | 6.5 | PURSUE | 3–5 |
| Kuda Bank | 8.8 | 8.0 | PURSUE | 4–6 |

Three of four scored PURSUE against low expectations, which looked like a
scoring failure. On review it was not. The expectations had been written under
the assumption that a struggling company is not worth pursuing — but
documenting *how* a company failed is a legitimate case study, and arguably a
more useful one for students than another success story.

The evaluation set has been rewritten accordingly: two expected ranges per
company instead of one, with a collapse *raising* the interest expectation and
lowering the reachability one.

Each expectation now records whether it was written **before or after** its
run. The four category C entries were revised after the fact and are therefore
weaker evidence than the sixteen still written blind. The scoreboard should
not pretend otherwise.

---

## 7. Operational

- **Usage page** (`/usage-page`) — per-model Gemini headroom, Tavily, Hunter
  and Apollo, with a live "about N more scouts today" figure. Counters persist
  in Redis, so Render's frequent restarts no longer reset the day to zero.
- **Admin gate** — `/usage` is behind a shared token compared with
  `hmac.compare_digest` and returns 404 rather than 401, so the endpoint does
  not advertise its own existence. *Not yet active in production: the token
  still needs setting in Render.*
- **Hunter validity** — "key is set" and "key works" are different facts, and
  a rejected key looked identical to a working one until the first lookup. The
  usage page now asks Hunter directly and reports working / rejected /
  could-not-check.
- **Sentry** — live, `send_default_pii=False`, secrets scrubbed, and the event
  is dropped entirely if scrubbing itself fails.

---

## Where it stands

**Working and verified:** two-score model, contact discovery across three
tiers, LinkedIn with explicit not-found reporting, coverage reporting, source
quality weighting, recency weighting, Hunter integration, background jobs with
polling, durable caching, admin gate (code), Sentry, usage tracking.

**Outstanding:**

1. `ADMIN_TOKEN` not yet set in Render — the usage page is publicly readable
2. 16 of 20 evaluation companies unrun (~96 Gemini calls ≈ 5 days of free quota)
3. `eval/failure_log.md` still largely a template
4. No audit mode — when a brief looks wrong, the only recourse is Render logs
5. Stage count is defined in two places (`jobs.py` and `index.html`)
6. Outreach agent — deliberately held until the evaluation is trustworthy
7. Discovery feature ("interesting companies in climate tech") — deliberately last
8. Apollo — dead end, their person-lookup endpoints are paid-only regardless of key

**The binding constraint remains Gemini's free tier:** ~6 calls per scout,
20 calls per day per model. Multi-model routing across four models with
fallback chains is what makes the tool usable at all.
