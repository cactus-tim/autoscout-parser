"""Application settings loaded from environment variables / .env file."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # OpenAI
    openai_api_key: str = Field(..., description="OpenAI API key")
    openai_model: str = Field("gpt-4.1-nano", description="OpenAI model name")

    # Telegram
    tg_token: str = Field("", description="Telegram bot token")
    tg_chat_id: str = Field("", description="Telegram chat/channel ID")

    # Google Sheets
    sheet_id: str = Field(..., description="Google Sheets spreadsheet ID")

    # Scoring
    score_notify_threshold: int = Field(8, description="Notify when score >= this value")

    # AutoScout24 throttle (seconds)
    as24_throttle_min: float = Field(2.0, description="Minimum seconds between page requests")
    as24_throttle_max: float = Field(6.0, description="Maximum seconds between page requests")

    # Enrichment
    as24_enrich: bool = Field(
        True,
        description="Fetch and parse detail pages to enrich listings with equipment/colour (set AS24_ENRICH=false to skip)",
    )

    # Integration tests
    integration_tests: bool = Field(False, description="Set to 1 to enable integration tests")
    integration_sheet_id: str = Field("", description="Google Sheets ID used by integration tests")

    # Paths
    brief_path: str = Field("brief.md", description="Path to the scoring brief Markdown file")
    creds_path: str = Field(
        "creds.json", description="Path to Google service-account credentials JSON"
    )
