"""What counts as a good source for an African company.

Generic web search rewards whoever publishes most and optimises hardest,
which for company names means the press-release wires. They republish a
company's own announcement verbatim, so they look like coverage while adding
no independent reporting — and they crowd out the outlets that actually cover
these markets.

Two lists, used in two places: to steer what search retrieves, and to grade
what comes back.
"""

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
