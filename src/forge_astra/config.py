from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ASTRA_", env_file=".env", extra="ignore")

    data_dir: Path = Path(".astra")
    output_dir: Path = Path("output")
    forge_seed: Path | None = None
    timezone: str = "UTC"
    llm_base_url: str = "http://localhost:8000/v1"
    llm_model: str = ""
    review_model: str = ""
    llm_api_key: SecretStr = Field(
        default=SecretStr(""),
        validation_alias=AliasChoices("ASTRA_LLM_API_KEY", "OPENAI_API_KEY"),
    )
    llm_extra_headers: dict[str, str] = Field(default_factory=dict, repr=False)
    llm_extra_body: dict = Field(default_factory=dict)
    llm_json_mode: bool = False
    llm_timeout: float = Field(default=180, gt=0)
    github_token: SecretStr = SecretStr("")
    poll_seconds: int = Field(default=21600, ge=60)
    release_lookback_days: int = Field(default=30, ge=1)
    scryfall_query: str = ""
    max_cards: int = Field(default=20, ge=1)
    max_revisions: int = Field(default=2, ge=0, le=5)
    examples_per_clause: int = Field(default=4, ge=1, le=10)

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        ZoneInfo(value)
        return value

    @field_validator("llm_base_url")
    @classmethod
    def valid_url(cls, value: str) -> str:
        if not value.startswith(("http://", "https://")):
            raise ValueError("LLM base URL must use http:// or https://")
        return value.rstrip("/")

    @property
    def db_path(self) -> Path:
        return self.data_dir / "astra.sqlite3"
