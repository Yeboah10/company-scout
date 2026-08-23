from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    google_api_key: str = ""
    tavily_api_key: str = ""
    llm_model: str = "gemini-3.6-flash"

    # The free tier's daily allowance is per model, not per project, so the
    # pipeline spreads itself across several. Each stage names a preferred
    # model and a fallback chain; when one model's day is spent the next is
    # used, instead of the whole run stopping while other budgets sit unused.
    #
    # Judgment stages get the stronger models; mechanical ones get lite.
    llm_model_resolver: str = "gemini-3.1-flash-lite"
    llm_model_extractor: str = "gemini-3.5-flash-lite"
    llm_model_analyst: str = "gemini-3.6-flash"
    llm_model_scorer: str = "gemini-3.5-flash"

    # Tried in order once a stage's preferred model is exhausted.
    llm_fallback_models: str = (
        "gemini-3.6-flash,gemini-3.5-flash,"
        "gemini-3.5-flash-lite,gemini-3.1-flash-lite"
    )

    @property
    def fallback_models(self) -> list[str]:
        return [m.strip() for m in self.llm_fallback_models.split(",") if m.strip()]
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

    # Optional. Person-first email lookup: given a named executive and a
    # company domain, returns their address. Free plan allows this only from
    # an account registered with a work email address.
    apollo_api_key: str = ""

    # Error reporting. Off unless a DSN is set.
    sentry_dsn: str = ""
    sentry_environment: str = "production"
    # Tagged on every event so a regression can be traced to a release.
    app_version: str = "0.8.0"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
