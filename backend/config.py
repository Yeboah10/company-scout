from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    anthropic_api_key: str = ""
    tavily_api_key: str = ""
    llm_model: str = "claude-sonnet-4-20250514"
    max_search_results: int = 10

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
