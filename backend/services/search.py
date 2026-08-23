from concurrent.futures import ThreadPoolExecutor

from tavily import TavilyClient

from backend.config import settings
from backend.models.schemas import SearchResult
from backend.services.sources import excluded_domains
from backend.services.usage import usage


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
        max_results = max_results or settings.max_search_results

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
        results = []
        for r in response.get("results", []):
            results.append(
                SearchResult(
                    query=query,
                    url=r.get("url", ""),
                    title=r.get("title", ""),
                    snippet=r.get("content", ""),
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
