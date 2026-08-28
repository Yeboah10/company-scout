"""Finding a way to actually reach a company.

A brief that says a company is worth pursuing, and then leaves you with no
way to contact anyone, has stopped one step short of being useful.

Two different things live here, and the distinction matters more than the
code does:

  FOUND     an address published somewhere public, with the page that
            published it recorded alongside it.
  INFERRED  a guess, built from the pattern other addresses at the same
            company follow. Never presented as fact.

An inferred address that turns out to belong to a different person is worse
than no address at all, so inference is only attempted when there is a real
observed pattern to extrapolate from, and every inferred value is labelled
wherever it is displayed.
"""

import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

from backend.services.sources import excluded_domains

# Deliberately conservative: better to miss an address than to invent one out
# of a string that merely looks like an email.
_EMAIL = re.compile(
    r"\b[A-Za-z0-9](?:[A-Za-z0-9._%+-]{0,62}[A-Za-z0-9])?@"
    r"(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,24}\b"
)

# Addresses that belong to the platform rather than the company, or which are
# obviously placeholders in documentation and templates.
_JUNK_LOCAL = {
    "example", "test", "noreply", "no-reply", "donotreply", "do-not-reply",
    "postmaster", "abuse", "webmaster", "hostmaster", "mailer-daemon",
    "your", "name", "email", "user", "username", "someone", "firstname",
}
_JUNK_DOMAINS = {
    "example.com", "example.org", "domain.com", "email.com", "yourcompany.com",
    "sentry.io", "wixpress.com", "godaddy.com", "squarespace.com",
    "schema.org", "w3.org", "google.com", "gstatic.com", "cloudflare.com",
}

# Generic company inboxes: useful to publish, but not a route to a person.
_ROLE_LOCALS = {
    "info", "contact", "hello", "hi", "support", "help", "sales", "press",
    "media", "admin", "enquiries", "inquiries", "careers", "jobs", "team",
    "office", "general", "marketing", "partnerships", "business",
    # Spiro publishes callcentre.ke@, callcentre.rw@ and callcentre.ug@ and
    # all three were counted as a named person's address.
    "callcentre", "callcenter", "communications", "comms", "pr", "news",
    "reception", "frontdesk", "bookings", "orders", "shop", "store",
    # Compliance, legal and security inboxes. Kuda's dpo@ and fraud@ were
    # being counted as a named person's address, which inflated how reachable
    # the company looked.
    "dpo", "privacy", "legal", "compliance", "security", "fraud", "risk",
    "billing", "accounts", "finance", "invoices", "hr", "recruitment",
    "complaints", "feedback", "service", "customercare", "customerservice",
    "newsletter", "subscribe", "unsubscribe", "notifications", "alerts",
}


@dataclass
class EmailFinding:
    email: str
    kind: str          # "personal" | "role"
    source_url: str | None = None
    person: str | None = None

    @property
    def local(self) -> str:
        return self.email.split("@", 1)[0]

    @property
    def domain(self) -> str:
        return self.email.split("@", 1)[1]


# Roughly how often each format turns up across companies generally. Used only
# when the company's own pattern could not be observed, and never presented as
# though it were specific to them.
#
# These are the shapes worth offering: beyond the top few the probability gets
# thin enough that listing more would be noise dressed as help.
COMMON_FORMATS = [
    ("{first}.{last}", "about a third of companies"),
    ("{first}", "common at smaller companies"),
    ("{f}{last}", "common at larger companies"),
    ("{first}{last}", "less common"),
]


@dataclass
class ContactReport:
    company_domain: str | None = None
    # False when `company_domain` itself is a guess (matched from search
    # results because no official website was confirmed), not just the
    # pattern applied to it. Every address built on top of an unconfirmed
    # domain is one guess stacked on another, and that matters more than
    # which format was used.
    domain_confirmed: bool = True
    found: list[EmailFinding] = field(default_factory=list)
    pattern: str | None = None
    pattern_basis: list[str] = field(default_factory=list)
    # Whether the pattern was confirmed against a person we know by name, or
    # merely read off the shape of an address. Both are useful; conflating
    # them would present a guess as an observation.
    pattern_confirmed: bool = False
    inferred: list[dict] = field(default_factory=list)
    note: str = ""


# Corporate suffixes stripped before matching a domain against a company
# name, so "MTN Nigeria Communications PLC" still matches "mtnonline.com" —
# "communications" and "plc" are not what makes a domain theirs.
_LEGAL_SUFFIXES = {
    "plc", "ltd", "limited", "inc", "incorporated", "corp", "corporation",
    "group", "holdings", "company", "co", "llc", "llp", "communications",
}


def _name_tokens(name: str) -> set[str]:
    words = re.split(r"[^A-Za-z0-9]+", name or "")
    return {w.lower() for w in words if len(w) > 2 and w.lower() not in _LEGAL_SUFFIXES}


# A handful of ccTLDs distinctive enough to signal a specific country. Not
# exhaustive — it exists only to catch the failure this was built for: two
# unrelated companies sharing a brand name in different countries. ReelFruit
# Nigeria (reelfruit.com) shares its exact name with reelfruit.ca (Canada)
# and reelfruit.co.za (South Africa); picking whichever came first in the
# search results would guess a real company's domain, just the wrong one.
# Deliberately narrow rather than a full ccTLD table: a false "no conflict"
# here just leaves the existing name-token check as the only guard, same as
# before this existed, so an incomplete list costs nothing.
_CCTLD_COUNTRY = {
    "ca": "canada", "co.za": "south africa", "za": "south africa",
    "co.uk": "united kingdom", "com.au": "australia", "au": "australia",
    "de": "germany", "fr": "france", "it": "italy", "es": "spain",
    "com.br": "brazil", "co.in": "india", "in": "india",
    "com.my": "malaysia", "sg": "singapore", "nl": "netherlands",
    "co.jp": "japan", "cn": "china", "ru": "russia", "co.kr": "south korea",
}


def _tld_country(host: str) -> str | None:
    """The country a domain's ccTLD names, if it's one of the recognised ones."""
    labels = host.split(".")
    for n in (2, 1):
        if len(labels) > n:
            claimed = _CCTLD_COUNTRY.get(".".join(labels[-n:]))
            if claimed:
                return claimed
    return None


def _tld_conflicts_with_country(host: str, company_country: str | None) -> bool:
    """Whether a domain's ccTLD names a country the company isn't in.

    Only fires when both the TLD and the company's country are known and
    they plainly disagree — a `.com`/`.org`/unrecognised TLD never conflicts,
    since most companies everywhere use them regardless of where they are.
    """
    if not company_country:
        return False
    claimed = _tld_country(host)
    return claimed is not None and claimed not in company_country.lower()


def _domain_matches_name(host: str, name_tokens: set[str]) -> bool:
    """Whether a domain plausibly belongs to the company, not merely mentions it.

    A news article about the company is not the company's domain, however
    prominently the company's name appears in its text — only the domain
    itself is checked here, against the company's own name tokens.
    """
    if not name_tokens:
        return False
    sld = host.split(".")[0]
    if sld in name_tokens:
        return True
    return any(len(tok) >= 3 and (tok in sld or sld in tok) for tok in name_tokens)


def company_domain(
    website: str | None,
    sources: list[str] | None = None,
    company_name: str | None = None,
    company_country: str | None = None,
) -> str | None:
    """The company's own domain, which anchors both extraction and inference.

    `website` is the confirmed case: the identification step named an
    official site. When it didn't — the LLM wasn't confident enough to
    commit to one from five search results, which happens often for
    smaller or less web-visible companies — `sources` and `company_name`
    let a domain still be found by looking at what was already searched,
    rather than giving up on contact-finding entirely. A candidate is only
    accepted when the domain itself carries the company's name, not merely
    a page that mentions the company, and known news/aggregator/social
    domains are excluded outright so a syndicated article can't be mistaken
    for the company's own site.

    `company_country`, when known, rules out a same-named company in the
    wrong place: ReelFruit Nigeria (reelfruit.com) shares its exact name
    with reelfruit.ca (Canada) and reelfruit.co.za (South Africa), both of
    which pass the name check just as cleanly as the real one. Without a
    country check, whichever happened to rank first in search results wins
    — a different real company's domain, guessed with total confidence.
    """
    if website:
        host = urlparse(website if "://" in website else f"https://{website}").netloc
        host = host.lower().removeprefix("www.")
        if host and "." in host:
            return host

    if sources and company_name:
        blocked = set(excluded_domains())
        tokens = _name_tokens(company_name)
        candidates = []
        for url in sources:
            try:
                host = urlparse(url if "://" in url else f"https://{url}").netloc
            except ValueError:
                continue
            host = host.lower().removeprefix("www.")
            if not host or "." not in host:
                continue
            if any(b in host for b in blocked):
                continue
            if not _domain_matches_name(host, tokens):
                continue
            if _tld_conflicts_with_country(host, company_country):
                continue
            candidates.append(host)

        if candidates:
            # A ccTLD that explicitly confirms the company's own country
            # outranks even .com — it's stronger evidence than the generic
            # default, not weaker. Failing that, .com is the safer bet over
            # an unrecognised TLD, which is more likely to belong to some
            # other, unrelated same-named company.
            def rank(h: str) -> int:
                tld_country = _tld_country(h)
                if company_country and tld_country and tld_country in company_country.lower():
                    return 0
                if h.endswith(".com"):
                    return 1
                return 2
            candidates.sort(key=rank)
            return candidates[0]

    return None


def _plausible(email: str) -> bool:
    local, _, domain = email.partition("@")
    local, domain = local.lower(), domain.lower()
    if domain in _JUNK_DOMAINS or local in _JUNK_LOCAL:
        return False
    # Image and asset filenames regularly contain an @ (e.g. logo@2x.png).
    if re.search(r"\.(png|jpe?g|gif|svg|webp|css|js)$", domain):
        return False
    if domain.endswith(".png") or "@2x" in email:
        return False
    # Spiro's contact page yielded `w@spironet.com`, which is markup bleeding
    # into the match rather than an address anyone reads.
    if len(local) < 2:
        return False
    return True


def extract_emails(text: str, domain: str | None) -> list[EmailFinding]:
    """Pull addresses out of page text, keeping only the company's own domain.

    Restricting to the company domain is what stops a journalist's byline or
    a PR agency's address being reported as a way to reach the company.
    """
    out: dict[str, EmailFinding] = {}
    for raw in _EMAIL.findall(text or ""):
        email = raw.lower().strip(".,;:")
        if not _plausible(email):
            continue
        if domain and not email.endswith(f"@{domain}"):
            continue
        out.setdefault(email, EmailFinding(email=email, kind=classify(email)))
    return list(out.values())


def classify(email: str) -> str:
    """Whether an address reaches a person or a function.

    The leading token decides it, not the whole local part: Spiro's
    `callcentre.ke@`, `callcentre.rw@` and `callcentre.ug@` are one inbox
    per country and every one of them was being read as a named person,
    which is a direct inflation of how reachable the company looked.
    """
    local = email.split("@", 1)[0].lower()
    if local in _ROLE_LOCALS:
        return "role"
    head = re.split(r"[._-]", local)[0]
    if head in _ROLE_LOCALS:
        return "role"
    return "personal"


def _tokens(name: str) -> tuple[str, str] | None:
    parts = [p for p in re.split(r"[^A-Za-z]+", name or "") if len(p) > 1]
    if len(parts) < 2:
        return None
    return parts[0].lower(), parts[-1].lower()


def detect_pattern(
    findings: list[EmailFinding], people: list[str]
) -> tuple[str | None, list[str], bool]:
    """Work out the company's address format from addresses actually observed.

    Only patterns confirmed against a known person's name are accepted. Without
    that check, "john@acme.com" could be read as {first} or as an arbitrary
    handle, and extrapolating the wrong reading produces addresses that look
    right and reach nobody.
    """
    name_pairs = [t for t in (_tokens(p) for p in people) if t]
    if not name_pairs:
        return _pattern_from_shape(findings)

    candidates = {
        "{first}.{last}": lambda f, l: f"{f}.{l}",
        "{first}{last}": lambda f, l: f"{f}{l}",
        "{f}{last}": lambda f, l: f"{f[0]}{l}",
        "{first}_{last}": lambda f, l: f"{f}_{l}",
        "{first}-{last}": lambda f, l: f"{f}-{l}",
        "{last}{f}": lambda f, l: f"{l}{f[0]}",
        "{first}": lambda f, l: f,
    }

    scores: dict[str, list[str]] = {}
    for finding in findings:
        if finding.kind != "personal":
            continue
        for first, last in name_pairs:
            for label, build in candidates.items():
                if finding.local == build(first, last):
                    scores.setdefault(label, []).append(finding.email)

    if scores:
        # Most-corroborated pattern wins; ties break toward the more specific
        # one (a bare {first} matches accidentally far more often than
        # {first}.{last}).
        best = max(scores.items(), key=lambda kv: (len(kv[1]), kv[0] != "{first}"))
        return best[0], best[1], True

    return _pattern_from_shape(findings)


# Separators that a two-token address is actually built from.
_SHAPES = {".": "{first}.{last}", "_": "{first}_{last}", "-": "{first}-{last}"}


def _pattern_from_shape(findings: list[EmailFinding]) -> tuple[str | None, list[str], bool]:
    """Read the format off an address whose owner we do not know by name.

    Spiro publishes flora.limukii@spironet.com. Flora is not among the people
    the research named, so the name check found nothing and no address was
    offered for any of the three executives who were named — even though the
    company's format was sitting there in plain sight.

    Two alphabetic tokens either side of a separator is a strong enough shape
    to extrapolate from. It is reported as a weaker basis than a confirmed
    match, because that is what it is.
    """
    votes: dict[str, list[str]] = {}
    for finding in findings:
        if finding.kind != "personal":
            continue
        for sep, pattern in _SHAPES.items():
            parts = finding.local.split(sep)
            if len(parts) == 2 and all(p.isalpha() and len(p) > 1 for p in parts):
                votes.setdefault(pattern, []).append(finding.email)
                break

    if not votes:
        return None, [], False
    best = max(votes.items(), key=lambda kv: len(kv[1]))
    return best[0], best[1], False


def apply_pattern(pattern: str, domain: str, person: str) -> str | None:
    tokens = _tokens(person)
    if not tokens or not pattern or not domain:
        return None
    first, last = tokens
    local = (
        pattern.replace("{first}", first)
        .replace("{last}", last)
        .replace("{f}", first[0])
    )
    if "{" in local:
        return None
    return f"{local}@{domain}"


def build_report(
    page_texts: list[tuple[str, str]],
    domain: str | None,
    people: list[str],
    domain_confirmed: bool = True,
) -> ContactReport:
    """Assemble found addresses, then infer only where a pattern is evidenced.

    `page_texts` is a list of (url, text) so every address keeps the page it
    came from — an address without provenance is indistinguishable from a
    guess, which is the exact confusion this module exists to prevent.
    """
    report = ContactReport(company_domain=domain, domain_confirmed=domain_confirmed)

    seen: dict[str, EmailFinding] = {}
    for url, text in page_texts:
        for finding in extract_emails(text, domain):
            if finding.email not in seen:
                finding.source_url = url
                seen[finding.email] = finding
    report.found = sorted(seen.values(), key=lambda f: (f.kind != "personal", f.email))

    # Attribute personal addresses to a named person where the local part
    # clearly contains their name.
    for finding in report.found:
        if finding.kind != "personal":
            continue
        for person in people:
            tokens = _tokens(person)
            if tokens and (tokens[1] in finding.local or tokens[0] in finding.local):
                finding.person = person
                break

    pattern, basis, confirmed = detect_pattern(report.found, people)
    report.pattern = pattern
    report.pattern_basis = basis
    report.pattern_confirmed = confirmed

    # A domain that was itself a guess makes every address built on it a
    # guess on top of a guess — said once here, then folded into each
    # entry's basis so the caveat travels wherever a single address is shown
    # on its own, not only in the report-level note. The exact phrase
    # "domain unconfirmed" is a deliberate marker: outreach.py checks for it
    # to keep these out of the "inferred" send tier, the same way it checks
    # for "common format" — a guessed domain is no more sendable-with-one-
    # confirmation than a guessed local part is.
    domain_caveat = "" if domain_confirmed else " — domain unconfirmed, inferred from search results"

    if pattern and domain:
        covered = {f.person for f in report.found if f.person}
        for person in people:
            if person in covered:
                continue
            guess = apply_pattern(pattern, domain, person)
            if guess and guess not in seen:
                report.inferred.append(
                    {
                        "person": person,
                        "email": guess,
                        "pattern": pattern,
                        "basis": (
                            "observed at this company"
                            if confirmed
                            else "matches the shape of an address this company "
                                 "publishes, but not confirmed against a known name"
                        ) + domain_caveat,
                    }
                )

    if report.found and report.inferred:
        how = ("observed" if report.pattern_confirmed
               else "apparent, unconfirmed")
        domain_note = f" {domain} was inferred, not confirmed as the company's site." if not domain_confirmed else ""
        report.note = (
            f"{len(report.found)} address(es) published publicly. "
            f"{len(report.inferred)} inferred from the {how} "
            f"{pattern}@{domain} pattern — unverified.{domain_note}"
        )
    elif report.found:
        domain_note = f" (at {domain}, inferred rather than confirmed as the company's own site)" if not domain_confirmed else ""
        report.note = f"{len(report.found)} address(es) published publicly{domain_note}."
    elif domain:
        # Nothing published and no pattern to extrapolate. Rather than stop
        # here, offer the formats companies most commonly use — explicitly as
        # generic possibilities, not as anything derived from this company.
        # Weaker than an observed pattern, and labelled so, but a starting
        # point beats a dead end when the alternative is guessing unaided.
        for person in people:
            tokens = _tokens(person)
            if not tokens:
                continue
            for fmt, prevalence in COMMON_FORMATS:
                guess = apply_pattern(fmt, domain, person)
                if guess:
                    report.inferred.append(
                        {
                            "person": person,
                            "email": guess,
                            "pattern": fmt,
                            "basis": f"common format — {prevalence}" + domain_caveat,
                        }
                    )

        if report.inferred:
            domain_note = (
                f" The domain itself ({domain}) was also inferred from search "
                "results rather than confirmed as the company's own site, so "
                "verify the domain as well as the name before using any of these."
                if not domain_confirmed else ""
            )
            report.note = (
                "No addresses were published anywhere findable, and none were "
                "available to establish this company's format. The addresses "
                "below are the formats companies most commonly use, applied to "
                "the names found — untested guesses, not derived from this "
                f"company. Verify before sending anything that matters.{domain_note}"
            )
        else:
            report.note = (
                "No published addresses found, and no names to build a "
                "candidate address from."
            )
    else:
        report.note = "No company domain identified, so no contact route found."

    return report
