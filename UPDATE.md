# Company Scout — update since the last status report

**Live:** https://scout.yeboah.works
**Repo:** github.com/Yeboah10/company-scout
**Covers:** everything after `STATUS.md` (23 August 2026) — twelve commits
**Written:** 23 August 2026

This is a delta, not a replacement. `STATUS.md` still describes what the tool
is, the stack, and the architecture; nothing there has been invalidated.

---

## 1. One score became two

**The problem.** The tool produced a single 0–10 "Scout Score" that tried to
answer two questions at once: *is this company interesting?* and *can I
actually reach anyone there?* Those pull in opposite directions. 54gene — an
African genomics startup that collapsed, with a CEO resignation and a court
injunction — is a genuinely good story and an impossible contact. A blended
number has to lie about one of them.

**The fix.** `CompanyBrief` now exposes two computed scores and a verdict:

- `interest_score` — worth your attention (story, case study, research value)
- `reachability_score` — can you get to a person, and are they still trading
- `verdict` — e.g. `PURSUE`, `WORTH WRITING ABOUT — NO WAY IN`

Reachability is deterministic rather than model-judged. It is zeroed outright
when `operational_status` is `defunct` or `winding_down`, then scaled by the
best contact route found: a named person's published address counts fully, a
role inbox 0.8, a LinkedIn profile 0.6, an inferred address 0.4, nothing 0.15.

54gene now reads **8.5 attention / 1.0 reach**, which is the answer a human
would give.

---

## 2. Contact discovery, with the guesswork labelled

Three tiers, enforced in the schema rather than in prose:

| Tier | Meaning |
|---|---|
| **Found** | Published somewhere public, with the page that published it recorded |
| **Inferred** | Built from an address format actually observed at this company |
| **Candidate** | The formats companies generally use, applied to known names — explicitly not derived from this company |

Emails are kept only if they are on the company's own domain, which stops a
journalist's byline or a PR agency's address being reported as a route in.
LinkedIn profiles are collected as URLs from search results and never fetched
— the pages sit behind a login, and the point is a link to click. Where no
profile is found the brief says so plainly and offers a search URL, so the
reader knows whether to look manually or give up.

**Hunter.io is live and verified.** The key was checked against Hunter's own
account endpoint rather than assumed to work. It is deliberately *not* called
on every run: a confirmed address format makes it redundant, so it is held
back for runs that came up short.

---

## 3. The brief now reports what it failed to find

The searcher has asked nine deliberate questions for a while — what they do,
how the product works, how they make money, funding, customers, geography,
people, recent news, and one explicitly adversarial query about layoffs and
shutdowns. Nothing measured whether any of them were answered.

Every search is now tagged with the area that asked for it. An area counts as
covered when a page that search surfaced went on to produce a claim the
extractor kept. That is weaker than "the question was answered" — it is "the
search found something worth extracting" — but it is true, costs zero LLM
calls, and cannot drift the way a keyword list would.

**It earned its place on the first live run.** The Spiro brief came back
8/9, missing *"How the product works"* — five search results, zero claims. For
a battery-swapping company that is the most interesting thing about it, and
the brief would otherwise have shipped that gap silently.

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
press. Kuda returned 46 sources, Spiro 42.

---

## 5. The evaluation's headline metric was measuring almost nothing

The most important correction in this report, because two previously reported
figures were wrong.

The findings matcher required *every* word of an expected finding to appear,
so "shutdown or major restructuring" failed unless the brief contained the
word "or". The first fix over-corrected — "insurance" matched "parametric
insurance" — so it was replaced with an LLM judge that compares by meaning.

Reported rates of 33% and 25% were artefacts. Re-checked across all four
category C companies, **all 13 expected findings are present**. The research
half of the tool works; the measurement of it did not.

---

## 6. Category C: the expectations were wrong, not the tool

Four companies chosen because the tool was *expected* to be unenthusiastic:

| Company | Attention | Reach | Verdict | Old expectation |
|---|---|---|---|---|
| Pula | 6.1 | 6.5 | PURSUE | 4–6 |
| 54gene | 8.5 | 1.0 | WORTH WRITING — NO WAY IN | 3–5 |
| Twiga Foods | 7.2 | 6.5 | PURSUE | 3–5 |
| Kuda Bank | 8.8 | 8.0 | PURSUE | 4–6 |

Three of four scored PURSUE against low expectations, which looked like a
scoring failure. On review it was not. The expectations assumed a struggling
company is not worth pursuing — but documenting *how* a company failed is a
legitimate case study, and arguably more useful to students than another
success story.

The evaluation set is rewritten accordingly: **two expected ranges per company
instead of one**, with a collapse *raising* the interest expectation and
lowering the reachability one.

Each expectation also records whether it was written **before or after** its
run. The four category C entries were revised after the fact and are therefore
weaker evidence than the sixteen still written blind. The scoreboard should
not pretend otherwise.

---

## 7. First end-to-end live run: Spiro

Run against production on the deployed code, not locally.

| | |
|---|---|
| Attention / Reach | **8.7 / 8.0 — PURSUE** |
| Expected (written blind) | 8–10 attention, 6–9 reach — **both in range** |
| Coverage | 8/9, gap: *How the product works* |
| Claims / Sources | 16 / 42 |
| Duration | **97 seconds** (down from 255–317s) |
| Contacts | 6 addresses found, 4 LinkedIn lookups |

The first blind expectation the tool has been measured against, and it landed.

---

## 8. Four bugs the Spiro run exposed — all fixed

**LinkedIn was excluded from its own search.** `search()` resolved
`exclude_domains` with `or`, so the explicit empty list the LinkedIn finder
passes to switch the filter off fell straight back to the default list — which
contains `linkedin.com`. Every profile lookup the tool has ever done ran with
LinkedIn excluded. That is why Spiro returned 0 of 4 profiles.

**Role inboxes counted as people.** The check matched the whole local part, so
Spiro's `callcentre.ke@`, `callcentre.rw@` and `callcentre.ug@` — one inbox per
country — each counted as a named person's address, as did `communications@`.
This inflates reachability directly. The leading token now decides it. Second
time this list has been wrong (Kuda's `dpo@` and `fraud@` were the first).

**`w@spironet.com` was offered as a contact.** Markup bleeding into the regex.
Single-character local parts are now rejected.

**The company's address format was visible and unused.** Spiro publishes
`flora.limukii@spironet.com`, but Flora was not among the people the research
named, so the name-confirmation check found nothing and none of the three
executives who *were* named got an address. Two alphabetic tokens either side
of a separator is now enough shape to extrapolate from, labelled as the weaker
basis it is.

**Bug class note:** two of these (`exclude_domains`, and the Hunter allowance
guard) were the same mistake — using `or` where `None` was meant, so a
legitimate falsy value silently fell through to a default. A sweep of the
remaining `or`-defaults found no further live instances.

---

## 9. A defect found but not yet fixed: people have no tenure

A Spiro brief listed **Jules Samain as co-CEO**. He was, and has since moved
to Acumen. The extractor read this sentence from Rest of World —

> "…co-CEO Jules Samain told Rest of World"

— and recorded a current role. `Person` carries no date and no
current/former status, so somebody quoted in an old article is presented
identically to somebody appointed last month.

This is not bad extraction. The sentence genuinely says he is co-CEO. It is a
missing field: the tool has no way to express *"this was true when the article
was written."*

For contrast, the same day's run on the fuller query correctly reported
**Anant Badjatya as Group CEO** (appointed 10 June 2026) and did not list
Samain as a person at all. The model is reading the sources correctly; the
schema cannot hold the answer.

**Verified independently:** Anant Badjatya was appointed Spiro's Group CEO on
10 June 2026, a newly created role, following a US$215M raise; Kaushik Burman
continues as CEO of the Mobility Business.

---

## 10. Operational

- **Admin gate is live.** `/usage` sits behind a shared token compared with
  `hmac.compare_digest`, returning **404 rather than 401** so the endpoint does
  not advertise its own existence. Verified from outside: no token → 404,
  wrong token → 404, correct token → 200.
- **Usage page** — per-model Gemini headroom, Tavily, Hunter and Apollo, with
  a live "about N more scouts today" figure. Counters persist in Redis, so
  Render's frequent restarts no longer reset the day to zero.
- **Hunter validity** — the page reports working / rejected / could-not-check,
  and now keeps our own call count alongside Hunter's so the two can be
  compared. Hunter reports a **50/month** allowance, not the 25 assumed from
  their pricing page.
- **Sentry** — live, `send_default_pii=False`, secrets scrubbed, and the event
  is dropped entirely if scrubbing itself fails.

---

## Where it stands

**Working and verified in production:** two-score model, contact discovery
across three tiers, coverage reporting, source quality weighting, recency
weighting, Hunter integration, background jobs with polling, durable caching,
admin gate, Sentry, usage tracking.

**Verified only in unit tests, awaiting a live run:** the four contact fixes
from section 8, LinkedIn profile discovery in particular.

**The binding constraint remains Gemini's free tier:** ~6 calls per scout,
20 calls per day per model. Multi-model routing across four models with
fallback chains is what makes the tool usable at all — roughly 3 fresh
companies per day, shared across every visitor.
