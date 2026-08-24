# Company Scout — update report

**Live:** https://scout.yeboah.works
**Repo:** github.com/Yeboah10/company-scout
**Covers:** 14 commits since the last report
**Written:** 24 August 2026

This replaces the previous update. The earlier report covered the two-score
model, contact discovery, coverage reporting and the evaluation corrections;
all of that still stands. What follows is everything since.

---

## 1. The product now has a front door

**Accounts.** Sign-in was a single operator password in an environment
variable — right for one person, wrong for more. There is now a `users` table,
a signup page, and a login page. Neither route replaces the other:
authentication checks the environment credential first (no database
dependency, so it still works if Postgres is unreachable), then the accounts
table. Passwords are PBKDF2-SHA256, salted per user, 200,000 rounds, compared
in constant time. Registering signs you straight in.

**Two accounts exist**, both created through the live signup form.

**One deliberate exception runs through it:** a shared report link stays
public. `/r/{key}`, the report endpoints and the explainer page need no
session. Sharing a finished brief is the point of the product, and a login
wall there would break the one thing a reader is meant to do with one.

**Welcome email** on signup, via Resend. Off unless configured, and a failed
send never turns a successful signup into a failed one. Currently sending from
Resend's sandbox address, which only delivers to the account owner —
`yeboah.works` DNS verification is pending, after which it moves to
`tebra@yeboah.works`.

---

## 2. Postgres, and reports that outlive a week

Briefs now write through to Postgres and are read back when the cache misses.
The Redis cache stays the fast path; it also forgets after seven days, which
meant every share link quietly expired. A link handed out last month now still
opens.

Two tables. `companies`, keyed by a normalised slug so "Spiro" and "Spiro
battery swapping" stop being two companies — which fixes the duplicate entries
that were appearing in Recently Scouted. `scout_runs`, one row per run with
the whole brief as JSONB plus the columns already known to be queried.

Deliberately not normalised further: the query patterns are not known yet, and
a schema built ahead of them is wrong in a way that is expensive to correct.
An `owner` column exists and is unused — adding it now is free, retrofitting
ownership onto existing rows later is not.

---

## 3. The redesign, and where it went wrong first

The Modernist direction from the design handoff is now implemented: Archivo
throughout, zero corner radius, 2px rules doing the organising, UM6P red for
action and ABS amber for one meaning only — *the evidence is weaker here*.

**The first attempt was wrong and was rejected.** It applied the design's
colours and typeface to the old layout, which is the worst of both: flat
colour with none of the structure that justifies it. The rebuild did the
layout properly.

**Dark mode is ours, not the handoff's** — the handoff has none, and a
light/dark toggle had already shipped. The first version used a warm
near-black that read as a sepia photograph; it is now neutral graphite, with
red and amber both lifted so they do not turn brown and ochre against it.

**Contrast is measured, not assumed.** Three colours exist only because the
obvious value failed: the base red is 3:1 on paper and fine for chrome but not
paragraphs; white on the logo amber is 4.26:1 and needed a hair darker to
clear AA; and the whole dark ramp.

### The Company Workspace

The report stopped being a long document and became a case file.

- **Header and score strip above the tabs**, so they never scroll away
- **Five scores**: attention, reachability, case-study potential, evidence
  confidence, coverage
- **The question poster** — the one full-bleed element, carrying the strongest
  signal's own question. On Spiro it surfaces *"what level of daily swap
  utilization is required for station-level breakeven?"*, which was previously
  buried three levels down a tab
- **Signal ledger** — rows that open in place, one at a time
- **"What we don't know"** — its own section, because a gap is a research lead

**Evidence confidence is computed, not invented.** The design specified "91%",
which no part of the backend produces. It now reports a HIGH/MEDIUM/LOW band
from the actual distribution of per-claim confidence, and shows its working:
"18 high, 0 low, of 24".

### The People module

Every piece of this already existed and none of it was shown together: people
with roles and tenure on one tab, their email addresses on another, LinkedIn
on a third. The question a reader actually has — *can I reach this person, and
should I trust that address* — could not be answered anywhere.

One card per person now carries the role, whether it is current, the best
route found, and a badge naming which kind of route it is. Ranked so the most
reachable is first. **Former staff are shown but never given a route**: an
address for someone who has left is the most damaging thing this page could
present as usable.

---

## 4. Resilience: three fallback chains

None of these compete for a call. Each catches one that would otherwise fail.

| Primary | Falls back to | Trigger |
|---|---|---|
| Gemini | Groq, then Cerebras | Every Gemini model's daily allowance spent |
| Tavily | Exa | Tavily's monthly plan exhausted |

**Cerebras is configured and live.** Groq is not — its signup was blocking, and
Cerebras alone covers the case.

**Exa was chosen over cheaper options** for a reason that outranks its
allowance: it supports `includeDomains` and `excludeDomains` natively. Those
are not conveniences here — one forces results from African tech press rather
than whatever ranks, the other keeps press-release wires out at source. Brave,
Serper and SerpAPI have neither, and emulating them with `site:` operators
breaks past a dozen domains, which would have degraded source quality quietly
rather than loudly.

**Two integrations were researched and rejected**, both after investigation
rather than assumption:

- **Manus AI.** Its API accepted five task-creation requests, returned success
  and a task ID for each, and created none of them — all five are absent from
  `task.list` and `task.detail` returns "task not found". Its documented
  `structured_output_schema` errors server-side in every valid form. And the
  one task that had genuinely run on the account cost 48 credits against a
  300/day refresh, meaning roughly six tasks a day — no better than the Gemini
  limit it was meant to relieve.
- **LinkedIn.** Premium grants no API access; it is an entirely separate
  developer track. No LinkedIn API at any tier, for any partner, at any price
  allows looking up a person by name and company. Their terms explicitly
  forbid combining LinkedIn content with other data, which is a direct
  description of what this tool does. The search-link approach already shipped
  turns out to be the only version of the feature that survives scrutiny.

---

## 5. The search budget was being spent on nothing

A scout used **29 Tavily searches**. Twelve of them — 41% — went to LinkedIn
person lookups that returned **zero profiles, across every live run**. LinkedIn
blocks the crawling that would put profile URLs into a search index, so no
number of searches could have succeeded.

The fallback those searches existed to avoid is what shipped anyway: a link the
reader clicks themselves, which needs no search to build.

```
Before:  29 searches per scout  →  34 companies/month on a 1,000 plan
After:   17 searches per scout  →  58 companies/month
```

Same allowance, 71% more work.

---

## 6. Tavily was exhausted and the usage page did not know

A scout failed with a bare `432` from Tavily. Two problems behind it.

**Our counter said 367 of 1,000 used. Tavily says 1,205.** The counter only
ever saw calls this process made, and was added long after the account started
being used — so it was reporting 633 searches of headroom that did not exist.
It now asks Tavily's own usage endpoint, with ours only as fallback.

**`432` is not a real HTTP status** and appears nowhere in Tavily's
documentation, so it arrived as an unrecognised error and reached the user as
*"something went wrong while researching this company"* — true, and useless,
because it invites a retry that cannot work. A spent plan now has its own error
type and a message explaining that search is the first step of every scout,
that this resets monthly rather than daily, and that saved reports still open.

---

## 7. The failure log, and what it shows

Fifteen real failures are now recorded with root causes. The individual bugs
matter less than the five patterns behind them:

**`or` where `None` was meant — 4 occurrences.** `x or default` silently
discards a legitimate falsy value. It excluded LinkedIn from its own search,
made the Hunter guard fall through to an optimistic count, and caused the first
snippet cleaner to revert itself on the exact page it was written for.

**Our count versus the provider's count — 3 occurrences.** Redis, Hunter and
Tavily all reported healthy while broken or exhausted. Every integration now
reports *configured* and *working* as separate facts.

**A schema missing a dimension the domain has — 2 occurrences.** One score
could not express "fascinating but unreachable". `Person` could not express
"this was true when it was written". Neither was a model failure — the model
had no field for the right answer.

**Precise numbers with nothing behind them — 2 occurrences.** The evaluation's
33% measured the matcher, not the pipeline. The design's "91% confidence" had
no source at all.

---

## Where it stands

**Live and working:** accounts, signup, welcome email, Postgres, the Modernist
redesign with dark mode, the Company Workspace, the People module, coverage
reporting, Cerebras fallback, Sentry, authoritative usage reporting.

**Blocked right now:** Tavily is exhausted (1,205/1,000) and the Exa fallback
key is set in Render but reporting `configured: false` — likely a variable-name
mismatch. Until that is resolved, no new research can run. Everything already
saved still works.

**Fixed but unverified against a live run:** industry disambiguation for
colliding company names, and snippet cleaning that strips scraped navigation.
Both are the diagnosed causes of a real coverage gap and both need one scout to
confirm.

**The largest outstanding item remains the evaluation** — 16 of 20 companies
unrun. Until it runs, the product's core claim, that it can correctly say some
companies are not worth pursuing, stays unverified at scale.
