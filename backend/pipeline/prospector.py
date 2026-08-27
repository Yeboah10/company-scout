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
from datetime import date
from urllib.parse import quote_plus

import httpx

from backend.models.schemas import (
    CompanyIdentity,
    ContactInfo,
    FoundEmail,
    InferredEmail,
    LinkedInProfile,
    Person,
    RoleStatus,
)
from backend.services.contacts import (
    EmailFinding,
    apply_pattern,
    build_report,
    company_domain,
)
from backend.services.apollo import (
    find_person_email,
    is_configured as apollo_configured,
    parse_person,
)
from backend.services.hunter import (
    domain_search,
    is_configured,
    parse_domain_search,
    remaining as hunter_remaining,
)
from backend.services import monitoring
from backend.services.usage import usage
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


def _lookups_left() -> int:
    """Hunter lookups still available, preferring Hunter's own figure."""
    theirs = hunter_remaining()
    return theirs if theirs is not None else usage.hunter_remaining()


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

        # Person profiles are NOT searched for, deliberately.
        #
        # This used to run two searches per person for up to six people —
        # twelve searches, 41% of a scout's entire search budget — and
        # measured across live runs it found zero profiles. Not few: zero.
        # LinkedIn blocks the crawling that would put profile URLs in a search
        # index, so the searches cannot succeed however many are spent.
        #
        # The fallback those searches existed to avoid is what shipped anyway:
        # a link the reader clicks themselves. That link needs no search to
        # build, so it is built directly. Same output, twelve fewer calls, and
        # the budget goes to research that returns something.
        #
        # The company page lookup above is kept — that one does work.
        for p in people[:6]:
            profiles.append(
                LinkedInProfile(
                    person=p.name,
                    role=p.role,
                    url=None,
                    found=False,
                    search_url=_linkedin_search_url(f"{p.name} {company.name}"),
                )
            )

        return profiles

    def find_contacts(
        self, company: CompanyIdentity, people: list[Person],
        source_urls: list[str] | None = None,
    ) -> ContactInfo:
        domain = company_domain(company.website)
        domain_confirmed = domain is not None

        if not domain and source_urls:
            # The identification step sometimes comes back with no confirmed
            # website — often for smaller or less web-visible companies — but
            # the search results gathered along the way frequently contain
            # the real site anyway. Rather than give up on every email route
            # at that point, fall back to a domain matched from those results
            # and say plainly, everywhere it's used, that it wasn't confirmed.
            domain = company_domain(None, sources=source_urls, company_name=company.name)
            if domain:
                print(
                    f"       > No confirmed website; using {domain} as a likely "
                    "domain, matched from search results",
                    flush=True,
                )

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

        # Somebody who has left is not a contact. Offering a guessed address
        # for a former executive is the most damaging thing this tool could
        # produce, so they are kept out of inference entirely rather than
        # inferred and then disclaimed.
        current = [p for p in people if p.name and p.status != RoleStatus.FORMER]
        departed = [p for p in people if p.name and p.status == RoleStatus.FORMER]
        names = [p.name for p in current]
        report = build_report(pages, domain, names, domain_confirmed=domain_confirmed)

        # Hunter is far more productive than reading public pages — most
        # companies publish a contact form rather than an address — but the
        # free tier allows 25 lookups a month against a Gemini budget that
        # permits roughly 90 scouts. Spent on every run it would be dry inside
        # a week, and dry on exactly the runs that needed it.
        #
        # So it is held back for the runs that came up short. A confirmed
        # address format is the outcome that makes it redundant: with one, an
        # address can be built for every named person already.
        hunter_emails: list[dict] = []
        hunter_pattern = None
        if is_configured():
            # Confirmed, not merely present. A pattern read off the shape of
            # one address is a guess, and a guess is exactly the situation
            # Hunter exists to settle — gating on `pattern` alone meant the
            # weaker the evidence, the more certainly Hunter was skipped.
            if report.pattern and report.pattern_confirmed:
                print(
                    f"       - Hunter not needed: {report.pattern}@{domain} "
                    f"already confirmed against a known name",
                    flush=True,
                )
            # Hunter's own count when it can be had, ours only as a fallback:
            # ours misses anything spent outside this process. Compared against
            # None rather than truthiness — a real remaining balance of zero is
            # exactly the case this guard exists for.
            elif _lookups_left() <= 0:
                # Announced rather than silently degraded: a run that quietly
                # skipped its best contact source looks identical to one where
                # Hunter simply found nothing.
                print("       ! Hunter monthly allowance spent — skipping lookup",
                      flush=True)
                monitoring.warn("Hunter allowance exhausted", domain=domain)
            else:
                hunter_emails, hunter_pattern = parse_domain_search(
                    domain_search(domain)
                )

        known = {f.email for f in report.found}

        # Apollo asks a different question — this named person's address,
        # rather than what exists at this domain — so it finds people Hunter
        # misses and is worth running alongside rather than instead.
        if apollo_configured():
            for person in people[:5]:  # each lookup costs a credit
                if person.name in {f.person for f in report.found if f.person}:
                    continue
                parts = [p for p in person.name.split() if len(p) > 1]
                if len(parts) < 2:
                    continue
                found = parse_person(
                    find_person_email(parts[0], parts[-1], domain)
                )
                if found and found["email"] not in known:
                    known.add(found["email"])
                    report.found.append(
                        EmailFinding(
                            email=found["email"],
                            kind=found["kind"],
                            source_url=found["source_url"],
                            person=found["person"] or person.name,
                        )
                    )

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
                    basis = "observed at this company"
                    if not domain_confirmed:
                        # Same caveat as build_report() applies elsewhere,
                        # and outreach.py's tier check looks for this exact
                        # phrase — a guessed domain stays candidate-tier
                        # regardless of which stage produced the pattern.
                        basis += " — domain unconfirmed, inferred from search results"
                    report.inferred.append(
                        {
                            "person": name,
                            "email": guess,
                            "pattern": hunter_pattern,
                            "basis": basis,
                        }
                    )
            report.note = (
                f"{len(report.found)} address(es) known publicly. "
                f"{len(report.inferred)} inferred from the "
                f"{hunter_pattern}@{domain} format — unverified."
            )

        linkedin = self._find_linkedin(company, people)

        today = date.today().isoformat()
        tenure = {
            p.name: (p.name, p.status.value, p.tenure_note) for p in people
        }

        if departed:
            who = ", ".join(p.name for p in departed)
            report.note += (
                f" No address was inferred for {who}: the evidence says they "
                f"have left, so an address there would reach the wrong person "
                f"or nobody."
            )

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
                    observed_on=today,
                )
                for f in report.found
            ],
            inferred=[
                InferredEmail(
                    person=i["person"],
                    email=i["email"],
                    pattern=i["pattern"],
                    basis=i.get("basis", "observed at this company"),
                    person_status=tenure.get(i["person"], (None, "unclear", None))[1],
                    person_tenure_note=tenure.get(i["person"], (None, None, None))[2],
                )
                for i in report.inferred
            ],
            note=report.note,
        )
