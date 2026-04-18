from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    api_base_url: str = "https://api.quanlaidian.com"
    data_root: Path = Path("data")
    file_ttl_days: int = 7
    log_level: str = "INFO"

    model_config = {"env_prefix": "QUOTE_"}


settings = Settings()
