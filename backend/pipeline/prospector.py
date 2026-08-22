"""Finding a route to a person at the company.

Costs search calls but no LLM calls, so it does not compete with the Gemini
free-tier budget that limits everything else in the pipeline.

Pages are read from anywhere, but only @company-domain addresses are kept.
Filtering on the address rather than on where it was published is what allows
a conference bio or a partner's press page to be useful without collecting a
journalist's or an agency's address alongside it.

LinkedIn profiles are collected as URLs only, from search results. Those pages
are never fetched: their content sits behind a login, and the point is a link
to click, not data taken from it.
"""

import re
from urllib.parse import quote_plus

import httpx

from backend.models.schemas import (
    CompanyIdentity,
    ContactInfo,
    FoundEmail,
    InferredEmail,
    LinkedInProfile,
    Person,
)
from backend.services.contacts import (
    EmailFinding,
    apply_pattern,
    build_report,
    company_domain,
)
from backend.services.hunter import domain_search, is_configured, parse_domain_search
from backend.services.search import SearchService

# Where organisations actually publish addresses.
CONTACT_QUERIES = [
    "contact us email",
    "about team leadership",
    "press media enquiries",
]

# The conventional locations for a contact address. Fetched directly because
# search engines return snippets, and an address sits in the page body.
CONTACT_PATHS = [
    "/contact",
    "/contact-us",
    "/about",
    "/about-us",
    "/team",
    "/",
]

_TAG = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.S | re.I)
_MARKUP = re.compile(r"<[^>]+>")

_LINKEDIN_PROFILE = re.compile(r"https?://[a-z]{0,3}\.?linkedin\.com/in/[A-Za-z0-9\-_%]+", re.I)
_LINKEDIN_COMPANY = re.compile(r"https?://[a-z]{0,3}\.?linkedin\.com/company/[A-Za-z0-9\-_%]+", re.I)


def _linkedin_search_url(terms: str) -> str:
    """A one-click LinkedIn people search, for when the profile wasn't found.

    Reporting "not found" without offering the next step just moves the work
    to the user without helping them do it.
    """
    return (
        "https://www.linkedin.com/search/results/people/?keywords="
        + quote_plus(terms.strip())
    )


def _name_matches(name: str, url: str, title: str) -> bool:
    """Guard against attributing a stranger's profile to a named executive.

    Search for a person at a company readily returns colleagues and namesakes;
    without this, the wrong person's profile gets presented as the CEO's.
    """
    parts = [p.lower() for p in re.split(r"[^A-Za-z]+", name or "") if len(p) > 1]
    if not parts:
        return False
    haystack = f"{url} {title}".lower()
    # Both first and last name must appear, in the URL slug or the page title.
    return all(p in haystack for p in (parts[0], parts[-1]))


def _visible_text(html: str) -> str:
    """Strip markup, keeping mailto: targets which are otherwise lost.

    Addresses are frequently only in an href, never in the visible text.
    """
    mailtos = re.findall(r'mailto:([^"\'>\s?]+)', html, re.I)
    text = _MARKUP.sub(" ", _TAG.sub(" ", html))
    return text + " " + " ".join(mailtos)


class Prospector:
    def __init__(self, search: SearchService):
        self.search = search

    def _fetch_own_pages(self, domain: str) -> list[tuple[str, str]]:
        """Read the company's own contact pages.

        A handful of ordinary GETs against pages published for exactly this
        purpose. Redirects are followed, failures are skipped quietly, and
        nothing is retried — a site that does not answer is not pursued.
        """
        pages: list[tuple[str, str]] = []
        headers = {
            "User-Agent": "CompanyScout/1.0 (+https://scout.yeboah.works)",
            "Accept": "text/html,application/xhtml+xml",
        }
        try:
            with httpx.Client(
                timeout=8.0, follow_redirects=True, headers=headers
            ) as client:
                for path in CONTACT_PATHS:
                    for scheme in ("https",):
                        url = f"{scheme}://{domain}{path}"
                        try:
                            r = client.get(url)
                        except httpx.HTTPError:
                            continue
                        if r.status_code == 200 and "html" in r.headers.get(
                            "content-type", ""
                        ):
                            pages.append((str(r.url), _visible_text(r.text)))
                        break
        except Exception as e:
            print(f"       ! Could not read company pages: {e}", flush=True)
        return pages

    def _find_linkedin(
        self, company: CompanyIdentity, people: list[Person]
    ) -> list[LinkedInProfile]:
        """Locate public LinkedIn URLs for the company and its named people.

        Only URLs are collected, from search results. LinkedIn pages are never
        fetched: their content sits behind a login and scraping it would breach
        their terms. A link the user clicks themselves is the whole point.
        """
        profiles: list[LinkedInProfile] = []
        seen: set[str] = set()

        def lookup(query: str, person: Person | None, want_company: bool) -> str | None:
            pattern = _LINKEDIN_COMPANY if want_company else _LINKEDIN_PROFILE
            # Two passes: a domain-restricted search, then an open one. Search
            # engines index LinkedIn poorly because LinkedIn blocks crawlers,
            # so profile URLs often surface only as links on other pages.
            attempts = [
                {"include_domains": ["linkedin.com"], "exclude_domains": []},
                {"exclude_domains": []},
            ]
            for kwargs in attempts:
                try:
                    results = self.search.search(query, max_results=6, **kwargs)
                except Exception as e:
                    print(f"       ! LinkedIn lookup failed: {e}", flush=True)
                    continue

                for r in results:
                    for haystack in (r.url, r.snippet or ""):
                        match = pattern.search(haystack)
                        if not match:
                            continue
                        url = match.group(0).rstrip("/")
                        if not url.startswith("http"):
                            url = f"https://{url}"
                        if url in seen:
                            continue
                        # Only attribute a profile to a person when their name
                        # is actually in it. Searching a name and a company
                        # readily returns colleagues and namesakes, and the
                        # wrong profile is worse than none.
                        if person is not None and not _name_matches(
                            person.name, url, r.title or ""
                        ):
                            continue
                        seen.add(url)
                        return url
            return None

        company_url = lookup(f"{company.name} {company.country or ''} linkedin", None, True)
        profiles.append(
            LinkedInProfile(
                url=company_url,
                found=bool(company_url),
                is_company_page=True,
                search_url=None if company_url else _linkedin_search_url(company.name),
            )
        )

        # Each person costs search calls, so cap it. Every one gets an entry
        # whether or not a profile was found.
        for p in people[:6]:
            url = lookup(f'"{p.name}" {company.name} linkedin', p, False)
            profiles.append(
                LinkedInProfile(
                    person=p.name,
                    role=p.role,
                    url=url,
                    found=bool(url),
                    search_url=None if url else _linkedin_search_url(
                        f"{p.name} {company.name}"
                    ),
                )
            )

        return profiles

    def find_contacts(
        self, company: CompanyIdentity, people: list[Person]
    ) -> ContactInfo:
        domain = company_domain(company.website)
        if not domain:
            # No domain means no email work is possible, but LinkedIn does not
            # depend on one and is often the only route that exists.
            return ContactInfo(
                linkedin=self._find_linkedin(company, people),
                note="No company website was identified, so no email address "
                     "could be found or inferred.",
            )

        # The company's own pages first: they are where addresses are actually
        # published, and search returns snippets rather than page bodies.
        pages = self._fetch_own_pages(domain)

        # Then the wider web. A company address is often published somewhere
        # other than the company's own site — a conference speaker bio, a
        # press contact on a partner's release, a regulatory listing.
        #
        # Widening *where we look* is safe because the filter that matters is
        # on the address itself: only @{domain} addresses are kept, so a
        # journalist's or an agency's address on the same page is discarded.
        for query in (
            f'"@{domain}" contact email',
            f"{company.name} press contact email",
            f"{company.name} CEO founder email address",
        ):
            pages.extend(self.search.fetch_pages(query, max_results=4))

        # And the company's own pages via search, for paths the conventional
        # list misses.
        for suffix in CONTACT_QUERIES:
            pages.extend(
                self.search.fetch_pages(
                    f"{company.name} {suffix}",
                    include_domains=[domain],
                    max_results=3,
                )
            )

        # Redirects mean the same page arrives under several paths.
        deduped: dict[str, str] = {}
        for url, text in pages:
            if url not in deduped or len(text) > len(deduped[url]):
                deduped[url] = text
        pages = list(deduped.items())

        names = [p.name for p in people if p.name]
        report = build_report(pages, domain, names)

        # Hunter, when configured, is far more productive than reading public
        # pages: most companies publish a contact form rather than an address.
        hunter_emails, hunter_pattern = parse_domain_search(domain_search(domain))
        known = {f.email for f in report.found}
        for e in hunter_emails:
            if e["email"] in known:
                continue
            known.add(e["email"])
            report.found.append(
                EmailFinding(
                    email=e["email"],
                    kind=e["kind"],
                    source_url=e["source_url"],
                    person=e["person"],
                )
            )
        # Hunter derives its pattern from a far larger sample than the handful
        # of addresses on a contact page, so prefer it when we have none.
        if hunter_pattern and not report.pattern:
            report.pattern = hunter_pattern
            report.inferred = []
            covered = {f.person for f in report.found if f.person}
            for name in names:
                if name in covered:
                    continue
                guess = apply_pattern(hunter_pattern, domain, name)
                if guess and guess not in known:
                    report.inferred.append(
                        {"person": name, "email": guess, "pattern": hunter_pattern}
                    )
            report.note = (
                f"{len(report.found)} address(es) known publicly. "
                f"{len(report.inferred)} inferred from the "
                f"{hunter_pattern}@{domain} format — unverified."
            )

        linkedin = self._find_linkedin(company, people)

        return ContactInfo(
            company_domain=report.company_domain,
            pattern=report.pattern,
            linkedin=linkedin,
            found=[
                FoundEmail(
                    email=f.email,
                    kind=f.kind,
                    source_url=f.source_url,
                    person=f.person,
                )
                for f in report.found
            ],
            inferred=[
                InferredEmail(
                    person=i["person"], email=i["email"], pattern=i["pattern"]
                )
                for i in report.inferred
            ],
            note=report.note,
        )
