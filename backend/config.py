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

    # When set, briefs are cached in Render Key Value instead of on disk.
    # Render's web service filesystem is ephemeral and spins down when idle,
    # so disk caching alone loses every saved report (and every share link)
    # on restart.
    redis_url: str = ""

    # Optional. When set, contact discovery also queries Hunter.io, which
    # returns a domain's published addresses and its address format. Without
    # it the pipeline falls back to reading public pages, which finds far less
    # because most companies now publish a contact form instead of an address.
    hunter_api_key: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
