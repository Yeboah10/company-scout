# Company Scout Failure Log

Every meaningful failure, and what it turned out to be caused by. This is the
map of how the system breaks.

A "failure" is anything where the system produced wrong, misleading, or
missing output — including cases where the *measurement* was wrong rather than
the pipeline, since a broken metric hides everything behind it.

## Failure Types

- **WRONG_FACT** — stated something factually incorrect
- **MISSING_KEY** — failed to find important, publicly available information
- **HALLUCINATION** — fabricated a claim not supported by any source
- **WRONG_COMPANY** — resolved to the wrong company
- **BAD_SOURCE** — cited a source that does not support the claim
- **STALE_INFO** — used outdated information when newer exists
- **FILLED_GAP** — made up data instead of saying "not established"
- **BAD_SCORE** — score clearly does not match the evidence
- **WRONG_PERSON** — attributed wrong role or title to a person
- **MISSED_NEGATIVE** — ignored public controversies or problems
- **BAD_MEASUREMENT** — the evaluation itself reported something untrue
- **SILENT_DEGRADE** — a feature stopped working without any error

---

## Log

| # | Company | Type | What happened | Root cause | Fix | Status |
|---|---------|------|---------------|------------|-----|--------|
| 1 | 54gene | BAD_SCORE | Scored 8.0 HIGH PRIORITY despite having shut down, with the collapse itself in the evidence | One blended score averaged "interesting" with "reachable". A collapse raises the first and destroys the second, so the mean was meaningless | Split into `interest_score` and `reachability_score`; `operational_status` zeroes reachability for defunct companies | Fixed |
| 2 | Spiro | WRONG_PERSON | Listed Jules Samain as co-CEO months after he had left for Acumen | `Person` carried no date and no current/former status, so someone quoted in an old article read identically to someone appointed last month | Added `status`, `role_start`, `role_end`, `as_of`, `tenure_note`; extractor asks what a source establishes *and as of when*; departed people get no inferred address | Fixed |
| 3 | Spiro | WRONG_COMPANY | The "how their product works" search returned App Store listings for Spiro.AI, an unrelated CRM — 4 of 5 results were the wrong company | Query was `{name} {country} {template}`; nothing in it said what industry the company is in | Added `industry` to the query template | Fixed, unverified live |
| 4 | Spiro | MISSING_KEY | The one correct technology source produced zero claims despite containing real detail (R&D centre, 150+ engineers, 30+ patents, IoT swap stations) | 350 characters of article followed by 1,700 characters of PR Newswire category menu. Extraction runs on the cheapest model by design and cannot find one paragraph inside 85% site furniture | `clean_snippet()` strips scraped navigation where snippets are created | Fixed, unverified live |
| 5 | Spiro | WRONG_PERSON | "Badjatya" and "Anant Badjatya" listed as two separate executives, each offered their own inferred email | Person dedup matched on exact name only | `_drop_partial_names()` drops single-word entries contained in a fuller name | Fixed |
| 6 | Kuda | WRONG_PERSON | `dpo@` and `fraud@` counted as named people's addresses, inflating reachability | Role-inbox list lacked compliance, legal and security terms | Extended `_ROLE_LOCALS` | Fixed |
| 7 | Spiro | WRONG_PERSON | `callcentre.ke@`, `callcentre.rw@`, `callcentre.ug@` and `communications@` all classified as personal addresses | The role check matched the whole local part, so `callcentre.ke` never matched `callcentre` | Leading token decides classification | Fixed |
| 8 | Spiro | BAD_SOURCE | `w@spironet.com` offered as a contact | Markup bleeding into the email regex; no minimum length on the local part | Reject local parts under 2 characters | Fixed |
| 9 | Spiro | MISSING_KEY | LinkedIn returned 0 of 6 person profiles, and no company page either | `search()` resolved `exclude_domains` with `or`, so the explicit empty list passed to disable filtering fell straight back to the default list — which contains `linkedin.com`. Every LinkedIn lookup ran with LinkedIn excluded | Compare against `None`. Company page now found | Partially fixed |
| 10 | Spiro | SILENT_DEGRADE | Person profiles still 0 after fix 9, and 12 searches per scout were being spent finding nothing | LinkedIn blocks the crawling that would put profile URLs into a search index. No number of searches can succeed | Person searches removed entirely; the search link they fell back to is built directly. 29 searches per scout became 17 | Closed as unfixable |
| 11 | Pula, Twiga | BAD_MEASUREMENT | Reported 33% and 25% findings rates that were pure artefact — real rates were 2/3 and 4/4 | Matcher required *every* word of an expected finding to appear, so "shutdown or major restructuring" failed unless the brief contained the word "or". The looser replacement then matched "insurance" inside "parametric insurance" | Replaced with an LLM judge comparing by meaning | Fixed |
| 12 | — | SILENT_DEGRADE | Redis reported as configured while every report was silently cached to disk and lost on restart | Two bugs hid it: the disk branch logged nothing, and `redis.from_url()` only parses a URL without connecting | Added `ping()` on init and `flush=True` logging | Fixed |
| 13 | — | SILENT_DEGRADE | Hunter counted 3 calls on our side, 0 on theirs | The format-from-shape fix set `report.pattern`, which tripped the "Hunter is redundant" gate — so the weaker the evidence, the more certainly Hunter was skipped | Gate on `pattern_confirmed`; every lookup records its outcome | Fixed |
| 14 | — | SILENT_DEGRADE | Usage page reported 633 Tavily searches remaining. Tavily reported 1,205 used against a 1,000 limit | Our counter only ever saw calls this process made, and was added long after the account started being used | Ask Tavily's own usage endpoint; ours is now only the fallback | Fixed |
| 15 | — | SILENT_DEGRADE | A spent Tavily plan reached the user as "something went wrong while researching this company" | Tavily answers an exhausted plan with `432`, which is not a real HTTP status and is undocumented, so it arrived as an unrecognised error | `SearchQuotaExhaustedError` with its own message and error kind; Exa added as fallback | Fixed |

---

## Patterns

The individual bugs matter less than these. Each has now caused several
distinct failures.

### `or` where `None` was meant — 4 occurrences

`x or default` silently discards a legitimate falsy value. It cost us LinkedIn
being excluded from its own search (#9), the Hunter allowance guard falling
through to an optimistic local count, `max_results=0` (latent), and the first
snippet cleaner reverting itself on the exact page it was written for.

**Rule:** when a caller can legitimately pass `0`, `[]` or `""`, compare
against `None` explicitly. A sweep found and closed the remaining instances.

### Our count versus the provider's count — 3 occurrences

Redis (#12), Hunter (#13) and Tavily (#14) all reported healthy while being
broken or exhausted. In every case a number we derived ourselves was believed
over the provider's own.

**Rule:** a number we calculate is a guess; the provider's number is the fact.
Every integration now reports *configured* and *working* as separate facts, and
prefers the provider's own usage endpoint where one exists.

### A schema missing a dimension the domain has — 2 occurrences

The single Scout Score could not express "fascinating but unreachable" (#1).
`Person` could not express "this was true when it was written" (#2). Both
produced confidently wrong output, and neither was a model failure — the model
had no field to put the right answer in.

**Rule:** when output is consistently wrong in one direction, check whether the
schema can represent the right answer at all before blaming extraction.

### Precise numbers with nothing behind them — 2 occurrences

The evaluation's 33% and 25% (#11) measured the matcher, not the pipeline. The
redesign specified a "91% evidence confidence" that no part of the backend
produces.

**Rule:** a number that looks measured must be traceable to something actually
counted. A band with visible working beats invented precision.

### Source quality

Press-release wires outranked African tech press until they were excluded at
the search API rather than filtered afterwards. Scraped site navigation drowned
real article text (#4). `impact-investor.com` was graded tier 1 on a bare
"investor" substring, fixed by anchoring tier-1 signals to URL paths.

### Search coverage gaps

Queries naming only a company and a country collide with unrelated products of
the same name (#3). The nine coverage areas exist so that a gap is reported
rather than silently absent — and that reporting is what surfaced both #3 and
#4 in the first place.
