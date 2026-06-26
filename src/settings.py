from os import environ
from pathlib import Path
from typing import ClassVar
from urllib.parse import quote_plus

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Project root: src/settings.py -> repo root is two levels up.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"

# Active environment (set by bot.py CLI flags), defaults to ``""``.
ENVIRONMENT = environ.get("ENVIRONMENT", "")
# Load base ``.env`` first, then overlay ``.env.<ENVIRONMENT>`` (overrides base).
# Missing files are silently ignored by pydantic-settings.
ENV_FILE: tuple[str, str] = (
    str(PROJECT_ROOT / ".env"),
    str(PROJECT_ROOT / f".env.{ENVIRONMENT}"),
)


class MySQLSettings(BaseSettings):
    """Environment-backed settings for the MySQL metadata database.

    Resolution order is:
    1. explicit ``DATABASE_URL`` when set;
    2. synthesized MySQL DSN from ``MYSQL*`` fields when complete.
    """

    database_url: str = Field(default="", validation_alias="DATABASE_URL")
    mysql_host: str = Field(default="", validation_alias="MYSQL_HOST")
    mysql_port: int = Field(default=3306, validation_alias="MYSQL_PORT")
    mysql_user: str = Field(default="", validation_alias="MYSQL_USER")
    mysql_password: str = Field(default="", validation_alias="MYSQL_PASSWORD")
    mysql_database: str = Field(default="", validation_alias="MYSQL_DATABASE")

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_file=ENV_FILE,
        extra="ignore",
    )

    @property
    def mysql_url(self) -> str:
        """Resolved MySQL URL synthesized from ``MYSQL*`` settings."""
        if not all(
            [
                self.mysql_host,
                self.mysql_user,
                self.mysql_password,
                self.mysql_database,
            ]
        ):
            return ""
        user = quote_plus(self.mysql_user)
        password = quote_plus(self.mysql_password)
        database = quote_plus(self.mysql_database)
        return f"mysql+pymysql://{user}:{password}@{self.mysql_host}:{self.mysql_port}/{database}"

    @property
    def preferred_url(self) -> str:
        """Configured primary database URL before availability probing."""
        if self.database_url:
            return self.database_url
        return self.mysql_url

    @property
    def url(self) -> str:
        """Backward-compatible alias for the configured primary database URL."""
        return self.preferred_url


mysql_settings = MySQLSettings()
