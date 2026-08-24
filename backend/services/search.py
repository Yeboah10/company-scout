from concurrent.futures import ThreadPoolExecutor

from tavily import TavilyClient

from backend.config import settings
from backend.models.schemas import SearchResult
from backend.services import exa_search, monitoring
from backend.services.sources import clean_snippet, excluded_domains
from backend.services.usage import usage


class SearchQuotaExhaustedError(Exception):
    """The Tavily plan's monthly allowance is spent.

    Separate from any Gemini quota error: they exhaust independently, they
    reset on different schedules, and telling a user "we are out of AI
    credits" when the real problem is search would send them to the wrong
    dashboard.
    """


class SearchService:
    def __init__(self):
        self.client = TavilyClient(api_key=settings.tavily_api_key)

    def search(
        self,
        query: str,
        max_results: int | None = None,
        include_domains: list[str] | None = None,
        exclude_domains: list[str] | None = None,
    ) -> list[SearchResult]:
        # Compared against None, not truthiness — the same class of bug as
        # the LinkedIn exclude_domains fix and the Hunter allowance guard.
        # Nobody passes max_results=0 today, so this was latent rather than
        # live, but "or" would silently ignore an explicit 0 and substitute
        # the default instead of returning nothing, which is exactly the
        # wrong behaviour for a caller that meant it.
        max_results = settings.max_search_results if max_results is None else max_results

        params = {
            "query": query,
            "max_results": max_results,
            "include_answer": False,
            # Basic depth returns whatever ranks highest, which for a company
            # name is dominated by SEO-heavy syndication.
            "search_depth": "advanced",
        }
        if include_domains:
            params["include_domains"] = include_domains
        # Wires and scraper directories are filtered at the source, not after,
        # because they otherwise consume a small results budget.
        #
        # Compared against None, not truthiness: an explicit empty list means
        # "exclude nothing", and `or` sent it straight back to the default.
        # LinkedIn is on that default list, so the LinkedIn profile finder —
        # which passes [] precisely to switch the filter off — had been
        # searching with LinkedIn excluded.
        params["exclude_domains"] = (
            excluded_domains() if exclude_domains is None else exclude_domains
        )

        try:
            usage.record_tavily()
            response = self.client.search(**params)
        except TypeError:
            # An older tavily-python may not accept every parameter; a plain
            # search is far better than no search.
            response = self.client.search(
                query=query, max_results=max_results, include_answer=False
            )
        except Exception as e:
            # Tavily answers an exhausted monthly plan with 432, which is not
            # a real HTTP status and appears nowhere in their documentation —
            # it surfaced here as a bare HTTPError and reached the user as
            # "something went wrong", which is true and useless. A spent plan
            # is not a crash: it has a cause, a reset date, and an action.
            if "432" in str(e):
                # Exa first, if it is configured. It supports the same
                # include/exclude domain semantics natively, so falling over
                # to it does not quietly degrade source quality the way a
                # site:-operator emulation would.
                if exa_search.is_configured():
                    print("       Tavily plan spent — falling back to Exa",
                          flush=True)
                    try:
                        results = exa_search.search(
                            query,
                            max_results=max_results,
                            include_domains=include_domains,
                            exclude_domains=params.get("exclude_domains"),
                        )
                        usage.record_exa()
                        return results
                    except Exception as exa_error:
                        print(f"       ! Exa fallback failed: {exa_error}",
                              flush=True)
                        monitoring.warn("Exa fallback failed",
                                        error=str(exa_error)[:200])

                raise SearchQuotaExhaustedError(
                    "The monthly search allowance is spent. Research cannot "
                    "run until it resets or the plan is upgraded."
                ) from e
            raise
        results = []
        for r in response.get("results", []):
            results.append(
                SearchResult(
                    query=query,
                    url=r.get("url", ""),
                    title=r.get("title", ""),
                    # Cleaned here, at the only place snippets are created, so every
                    # downstream consumer — extraction, the evidence
                    # excerpt in a brief, the precision audit — sees the
                    # article rather than the page furniture around it.
                    snippet=clean_snippet(r.get("content", "")),
                    published_date=r.get("published_date"),
                    score=r.get("score"),
                )
            )
        return results

    def fetch_pages(
        self, query: str, include_domains: list[str] | None = None, max_results: int = 5
    ) -> list[tuple[str, str]]:
        """Search and return (url, full page text) rather than just snippets.

        Contact details live in page bodies, not in search snippets, so this
        asks for the raw content. Costs a search call, not an LLM call.
        """
        try:
            params = {
                "query": query,
                "max_results": max_results,
                "include_answer": False,
                "include_raw_content": True,
                "search_depth": "advanced",
            }
            if include_domains:
                params["include_domains"] = include_domains
            usage.record_tavily()
            response = self.client.search(**params)
        except Exception as e:
            print(f"       ! Page fetch failed for '{query}': {e}", flush=True)
            return []

        pages = []
        for r in response.get("results", []):
            text = r.get("raw_content") or r.get("content") or ""
            if text:
                pages.append((r.get("url", ""), text))
        return pages

    def search_multiple(
        self,
        queries: list[str] | list[tuple[str, list[str] | None]],
        max_results_per_query: int = 5,
        areas: list[str] | None = None,
    ) -> list[SearchResult]:
        """Run queries concurrently. An entry may be a bare query string, or a
        (query, include_domains) pair to restrict it to specific publishers.

        `areas`, when given, names what each query was asked on behalf of and
        is recorded on every result it returns, so the brief can later report
        which questions went unanswered."""
        # The queries are independent, so run them concurrently. Results are
        # then merged in the original query order to keep output stable.
        def run(item) -> list[SearchResult]:
            query, include = item if isinstance(item, tuple) else (item, None)
            try:
                return self.search(
                    query,
                    max_results=max_results_per_query,
                    include_domains=include,
                )
            except Exception as e:
                # One failed query shouldn't sink the whole research run.
                print(f"       ! Search failed for '{query}': {e}", flush=True)
                return []

        with ThreadPoolExecutor(max_workers=len(queries) or 1) as pool:
            per_query = list(pool.map(run, queries))

        all_results = []
        by_url: dict[str, SearchResult] = {}
        for i, results in enumerate(per_query):
            area = areas[i] if areas and i < len(areas) else None
            for r in results:
                existing = by_url.get(r.url)
                if existing is None:
                    if area:
                        r.areas = [area]
                    by_url[r.url] = r
                    all_results.append(r)
                elif area and area not in existing.areas:
                    # Credit every area that surfaced the page, not just the
                    # first: deduplicating the URL should not deduplicate the
                    # fact that two different questions led here.
                    existing.areas.append(area)
        return all_results
