from backend.models.schemas import CompanyIdentity, SearchResult
from backend.services.llm import LLMService
from backend.services.search import SearchService

SYSTEM_PROMPT = """You are a company identification specialist. Given search results about a company query, identify the company and return structured JSON.

Return ONLY valid JSON in this exact format:
{
    "name": "Official company name",
    "website": "https://company-website.com or null",
    "country": "Country of headquarters or null",
    "industry": "Primary industry or null",
    "description": "One-sentence description of what the company does or null",
    "founded_year": 2020 or null
}

Rules:
- Use the official company name, not abbreviations
- Only include information you can confirm from the search results
- Use null for anything uncertain or not found
- For African companies, be specific about the country (not just "Africa")
"""


class CompanyResolver:
    def __init__(self, search: SearchService, llm: LLMService):
        self.search = search
        self.llm = llm

    def resolve(self, query: str) -> tuple[CompanyIdentity, list[SearchResult]]:
        search_results = self.search.search(f"{query} company official website", max_results=5)

        snippets = "\n\n".join(
            f"Title: {r.title}\nURL: {r.url}\nSnippet: {r.snippet}"
            for r in search_results
        )

        user_prompt = f'Identify this company: "{query}"\n\nSearch results:\n{snippets}'

        data = self.llm.extract_structured(SYSTEM_PROMPT, user_prompt)
        identity = CompanyIdentity(**data)

        if not identity.name or identity.name.lower() == "null":
            identity.name = query

        return identity, search_results
