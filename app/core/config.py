from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "Hospital Bulk Processing API"
    app_version: str = "1.0.0"
    debug: bool = False

    # External API
    hospital_api_base_url: str = "https://hospital-directory.onrender.com"
    hospital_api_timeout: float = 30.0

    # Database
    database_url: str = "sqlite+aiosqlite:///./hospital_bulk.db"

    # Processing limits
    max_csv_rows: int = 20
    http_concurrency_limit: int = 5  # max parallel calls to external API

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
