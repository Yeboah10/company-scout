from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    google_api_key: str = ""
    tavily_api_key: str = ""
    llm_model: str = "gemini-3.6-flash"
    max_search_results: int = 10

    # Caching. A full scout costs ~6 Gemini calls, and the free tier allows
    # 20/day, so serving repeat lookups from cache is what makes the tool
    # usable at all.
    cache_enabled: bool = True
    cache_dir: str = ".cache"
    cache_ttl_days: int = 7

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
