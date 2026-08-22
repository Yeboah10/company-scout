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


@dataclass
class ContactReport:
    company_domain: str | None = None
    found: list[EmailFinding] = field(default_factory=list)
    pattern: str | None = None
    pattern_basis: list[str] = field(default_factory=list)
    inferred: list[dict] = field(default_factory=list)
    note: str = ""


def company_domain(website: str | None, sources: list[str] | None = None) -> str | None:
    """The company's own domain, which anchors both extraction and inference."""
    if website:
        host = urlparse(website if "://" in website else f"https://{website}").netloc
        host = host.lower().removeprefix("www.")
        if host and "." in host:
            return host
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
        local = email.split("@", 1)[0]
        kind = "role" if local in _ROLE_LOCALS else "personal"
        out.setdefault(email, EmailFinding(email=email, kind=kind))
    return list(out.values())


def _tokens(name: str) -> tuple[str, str] | None:
    parts = [p for p in re.split(r"[^A-Za-z]+", name or "") if len(p) > 1]
    if len(parts) < 2:
        return None
    return parts[0].lower(), parts[-1].lower()


def detect_pattern(findings: list[EmailFinding], people: list[str]) -> tuple[str | None, list[str]]:
    """Work out the company's address format from addresses actually observed.

    Only patterns confirmed against a known person's name are accepted. Without
    that check, "john@acme.com" could be read as {first} or as an arbitrary
    handle, and extrapolating the wrong reading produces addresses that look
    right and reach nobody.
    """
    name_pairs = [t for t in (_tokens(p) for p in people) if t]
    if not name_pairs:
        return None, []

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

    if not scores:
        return None, []

    # Most-corroborated pattern wins; ties break toward the more specific one
    # (a bare {first} matches accidentally far more often than {first}.{last}).
    best = max(scores.items(), key=lambda kv: (len(kv[1]), kv[0] != "{first}"))
    return best[0], best[1]


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
) -> ContactReport:
    """Assemble found addresses, then infer only where a pattern is evidenced.

    `page_texts` is a list of (url, text) so every address keeps the page it
    came from — an address without provenance is indistinguishable from a
    guess, which is the exact confusion this module exists to prevent.
    """
    report = ContactReport(company_domain=domain)

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

    pattern, basis = detect_pattern(report.found, people)
    report.pattern = pattern
    report.pattern_basis = basis

    if pattern and domain:
        covered = {f.person for f in report.found if f.person}
        for person in people:
            if person in covered:
                continue
            guess = apply_pattern(pattern, domain, person)
            if guess and guess not in seen:
                report.inferred.append(
                    {"person": person, "email": guess, "pattern": pattern}
                )

    if report.found and report.inferred:
        report.note = (
            f"{len(report.found)} address(es) published publicly. "
            f"{len(report.inferred)} inferred from the observed "
            f"{pattern}@{domain} pattern — unverified."
        )
    elif report.found:
        report.note = f"{len(report.found)} address(es) published publicly."
    elif domain:
        report.note = (
            "No published addresses found, and no observed pattern to infer "
            "from. Guessing a format without evidence would be a coin flip."
        )
    else:
        report.note = "No company domain identified, so no contact route found."

    return report
