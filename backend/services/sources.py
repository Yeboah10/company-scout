"""What counts as a good source for an African company.

Generic web search rewards whoever publishes most and optimises hardest,
which for company names means the press-release wires. They republish a
company's own announcement verbatim, so they look like coverage while adding
no independent reporting — and they crowd out the outlets that actually cover
these markets.

Two lists, used in two places: to steer what search retrieves, and to grade
what comes back.
"""

import re

# Independent outlets that actually report on African business and tech.
# Searched explicitly, because relying on them to surface organically is how
# they end up buried under wire copy.
AFRICAN_TECH_PRESS = [
    "techcabal.com",
    "technext24.com",
    "condia.co",
    "techpoint.africa",
    "disrupt-africa.com",
    "ventureburn.com",
    "itweb.africa",
    "businessday.ng",
    "nation.africa",
    "theafricareport.com",
    "african.business",
    "stearsng.com",
    "semafor.com",
    "restofworld.org",
    "bizcommunity.com",
]

# Wire services and syndication. A company announcement reprinted verbatim is
# the company talking, not a source corroborating it.
PRESS_RELEASE_WIRES = [
    "prnewswire.com",
    "globenewswire.com",
    "businesswire.com",
    "einpresswire.com",
    "einnews.com",
    "accesswire.com",
    "openpr.com",
    "pressreleasepoint.com",
    "prweb.com",
    "newswire.com",
    "24-7pressrelease.com",
    "issuewire.com",
    "prlog.org",
    "streetinsider.com",
    "manilatimes.net",
]

# Aggregators and content farms: no original reporting, frequently stale.
LOW_VALUE_DOMAINS = [
    "crunchbase.com",
    "pitchbook.com",
    "zoominfo.com",
    "rocketreach.co",
    "signalhire.com",
    "lusha.com",
    "leadiq.com",
    "apollo.io",
    "owler.com",
    "zippia.com",
    "glassdoor.com",
    "indeed.com",
    "linkedin.com",
    "tracxn.com",
    "cbinsights.com",
    "startupintros.com",
    "growjo.com",
    "latka.com",
    # Social profiles are the company's own marketing, and their snippets
    # carry almost no extractable fact.
    "facebook.com",
    "instagram.com",
    "twitter.com",
    "x.com",
    "tiktok.com",
    "youtube.com",
    "pinterest.com",
    "reddit.com",
]

# Regulators, exchanges and filings — the strongest evidence there is.
TIER_1_SIGNALS = [
    ".gov",
    "gov.",
    "sec.gov",
    "cbn.gov.ng",
    "centralbank",
    "nse.com.ng",
    "jse.co.za",
    "cma.or.ke",
    # Path-anchored rather than bare words: "investor" on its own promoted
    # impact-investor.com to the same tier as a regulatory filing.
    "/investor-relations",
    "/investors/",
    "investor-relations.",
    "/annual-report",
    "/regulatory",
    "/filings",
]


def is_press_release(url: str, publisher: str | None = None) -> bool:
    """True for wire-service syndication, which should never be graded as
    independent corroboration."""
    haystack = f"{url} {publisher or ''}".lower()
    return any(domain in haystack for domain in PRESS_RELEASE_WIRES)


def excluded_domains() -> list[str]:
    """Domains worth keeping out of search results entirely.

    Wires are excluded rather than merely downranked: they take up result
    slots that a small max_results budget cannot spare, and anything they
    carry is the company's own announcement, which the company's own site
    and real coverage will both report anyway.
    """
    return PRESS_RELEASE_WIRES + LOW_VALUE_DOMAINS


# ---------------------------------------------------------------------------
# Snippet cleaning
#
# Search snippets arrive with the page's navigation scraped in alongside the
# article. A PR Newswire release about Spiro carried 350 characters of real
# content followed by 1,700 characters of site menu — "## Energy & Natural
# Resources ## Energy & Natural Resources Overview ## View All Energy &
# Natural Resources", repeated for a dozen unrelated categories.
#
# That matters because extraction runs on the cheapest model by design, and
# asking it to find one real paragraph inside 85% site furniture fails
# silently: no error, no logged failure, just nothing extracted. The Spiro
# brief lost its only good technology source exactly this way.
#
# Conservative on purpose. It removes what is unambiguously chrome and leaves
# anything it is unsure about, because dropping real evidence is a worse
# failure than passing along some noise.

# Menu items scraped as markdown headings: short, and overwhelmingly the
# repeated "Overview" / "View All" pattern of a site's own category nav.
_NAV_HEADING = re.compile(r"^#{1,6}\s*(.{0,60})$")
_NAV_WORDS = ("overview", "view all", "browse", "homepage", "sign in",
              "log in", "subscribe", "newsletter", "cookie", "menu",
              "navigation", "skip to", "search")


def clean_snippet(text: str) -> str:
    """Strip scraped site navigation, keeping the article.

    Returns the text unchanged if cleaning would remove most of it — that
    would mean the heuristic misread an article as chrome, and passing the
    original through is the safer failure.
    """
    if not text:
        return text

    kept: list[str] = []
    seen: set[str] = set()
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue

        heading = _NAV_HEADING.match(stripped)
        if heading:
            label = heading.group(1).strip().lower()
            # A short heading whose text is a nav word, or which has already
            # appeared, is site furniture rather than part of the article.
            if any(w in label for w in _NAV_WORDS) or label in seen:
                continue
            seen.add(label)

        kept.append(stripped)

    # A run of three or more headings with no prose between them is a menu.
    # Real articles put text under their headings; navigation does not.
    deduped: list[str] = []
    run: list[str] = []
    for line in kept:
        if _NAV_HEADING.match(line):
            run.append(line)
            continue
        if len(run) < 3:
            deduped.extend(run)
        run = []
        deduped.append(line)
    if len(run) < 3:
        deduped.extend(run)

    cleaned = "\n".join(deduped).strip()

    # The guard is about prose kept, not proportion removed. A first attempt
    # used "reverted if more than 70% was stripped", which failed on exactly
    # the page this exists for: the PR Newswire release genuinely is ~85%
    # navigation, the heuristic was right, and the percentage floor threw the
    # correct answer away. What actually matters is whether real sentences
    # survived — so that is what is measured.
    prose = " ".join(
        line for line in cleaned.split("\n") if not _NAV_HEADING.match(line)
    ).strip()
    if len(prose) < 120:
        return text
    return cleaned
