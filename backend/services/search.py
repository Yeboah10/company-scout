from concurrent.futures import ThreadPoolExecutor

from tavily import TavilyClient

from backend.config import settings
from backend.models.schemas import SearchResult


class SearchService:
    def __init__(self):
        self.client = TavilyClient(api_key=settings.tavily_api_key)

    def search(self, query: str, max_results: int | None = None) -> list[SearchResult]:
        max_results = max_results or settings.max_search_results
        response = self.client.search(
            query=query,
            max_results=max_results,
            include_answer=False,
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

    def search_multiple(self, queries: list[str], max_results_per_query: int = 5) -> list[SearchResult]:
        # The queries are independent, so run them concurrently. Results are
        # then merged in the original query order to keep output stable.
        def run(query: str) -> list[SearchResult]:
            try:
                return self.search(query, max_results=max_results_per_query)
            except Exception as e:
                # One failed query shouldn't sink the whole research run.
                print(f"       ! Search failed for '{query}': {e}")
                return []

        with ThreadPoolExecutor(max_workers=len(queries) or 1) as pool:
            per_query = list(pool.map(run, queries))

        all_results = []
        seen_urls = set()
        for results in per_query:
            for r in results:
                if r.url not in seen_urls:
                    seen_urls.add(r.url)
                    all_results.append(r)
        return all_results
