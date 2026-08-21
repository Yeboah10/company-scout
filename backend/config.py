from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    google_api_key: str = ""
    tavily_api_key: str = ""
    llm_model: str = "gemini-3.6-flash"
    max_search_results: int = 10

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
