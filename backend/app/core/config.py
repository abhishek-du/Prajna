"""Configuration. Fails fast and loudly.

Two rules this module exists to enforce:

1. No working defaults for anything that matters. V1's Settings declared
   DATABASE_URL = "postgresql+asyncpg://postgres:password@localhost:5432/autotrade_pro",
   so a misconfigured process started successfully and pointed somewhere
   unintended. Here, a missing required key raises at import.

2. V2 reads only its own .env. It never imports, inherits, or falls back to
   V1's configuration (constraint #1).
"""

from __future__ import annotations

import functools
import pathlib

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.errors import ConfigError, DatabaseIsolationError

BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[2]

# Databases V2 must never address, under any configuration.
FORBIDDEN_DATABASES = frozenset({"autotrade_pro", "autotrade_test"})


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )

    # ── database ────────────────────────────────────────────────────────────
    PRAJNA_DATABASE_URL: str
    PRAJNA_TEST_DATABASE_URL: str = ""

    # ── write authorization (constraint #10) ────────────────────────────────
    PRAJNA_WRITE_TOKEN: str = ""

    # ── Upstox: the only market-data vendor in V2 ───────────────────────────
    UPSTOX_API_KEY: str = ""
    UPSTOX_API_SECRET: str = ""
    UPSTOX_REDIRECT_URL: str = ""
    UPSTOX_CLIENT_ID: str = ""
    UPSTOX_USERNAME: str = ""
    UPSTOX_PIN: str = ""
    UPSTOX_TOTP_SECRET: str = ""

    # ── paths ───────────────────────────────────────────────────────────────
    PRAJNA_ARCHIVE_DIR: str = "var/archive"
    PRAJNA_LOG_DIR: str = "var/logs"

    # ── runtime ─────────────────────────────────────────────────────────────
    PRAJNA_ENV: str = "dev"
    PRAJNA_LOG_LEVEL: str = "INFO"

    # Stage 7 concern. The tick_archive table exists from migration 0001 so the
    # contract is fixed, but the writer stays off until execution needs it.
    PRAJNA_TICK_PERSISTENCE_ENABLED: bool = Field(default=False)
    # Share of Upstox's documented per-user rate limits THIS process may use.
    # The quota is per user, not per process: when two REST processes run at
    # once (e.g. the B1/B2 poller in market hours and an ingest job), their
    # fractions must add up to <= 0.9. Default 0.9 = the one-process rule.
    PRAJNA_UPSTOX_RATE_FRACTION: float = Field(default=0.9, gt=0.0, le=0.9)
    # Stage 2 live/continuous mode (feeding downstream stages in real time).
    # False by default and until explicitly approved: Stage 2 then only runs as
    # batch processing, and nothing in it can reach signals, orders or brokers.
    STAGE2_LIVE_ENABLED: bool = Field(default=False)
    # Stage 3 (feature engineering) production execution and feature backfill.
    # False by default and until explicitly approved: Stage 3 then only computes
    # in dry-run (read-only); app.features.locks refuses every write. Enabling a
    # flag is necessary, never sufficient (Stage 1 COMPLETE, Stage 2 PASS,
    # decisions approved, no kill switch and a write token are also required).
    PRAJNA_STAGE3_ENABLED: bool = Field(default=False)
    PRAJNA_STAGE3_BACKFILL_ENABLED: bool = Field(default=False)
    # Multi-source news (decisions NEWS-*). All false by default; DRY_RUN polling
    # needs none of them. One flag PER SOURCE enables database writes for that
    # source only (there is deliberately no switch that enables every source), and
    # a flag is necessary, never sufficient (app.news.locks). MULTI_SOURCE: rows
    # written in PRODUCTION mode become visible to Stage 2/3/API. LIVE_STREAM: the
    # news stream (not built). Upstox's Stage 1 ingestion is NOT governed here;
    # PRAJNA_NEWS_UPSTOX_ENABLED only concerns its projection into the new layer.
    PRAJNA_NEWS_UPSTOX_ENABLED: bool = Field(default=False)
    PRAJNA_NEWS_NSE_ENABLED: bool = Field(default=False)
    PRAJNA_NEWS_ET_ENABLED: bool = Field(default=False)
    PRAJNA_NEWS_BS_ENABLED: bool = Field(default=False)
    PRAJNA_NEWS_BL_ENABLED: bool = Field(default=False)
    PRAJNA_NEWS_MINT_ENABLED: bool = Field(default=False)
    PRAJNA_NEWS_CNBC_ENABLED: bool = Field(default=False)
    PRAJNA_NEWS_IE_ENABLED: bool = Field(default=False)
    PRAJNA_NEWS_SEBI_ENABLED: bool = Field(default=False)
    # optional AI enrichment of news (app.news.ai): off unless enabled AND a model id
    # is set; AWS credentials come only from the process's standard AWS chain
    PRAJNA_NEWS_AI_ENABLED: bool = Field(default=False)
    PRAJNA_NEWS_AI_MODEL_ID: str | None = Field(default=None)
    PRAJNA_NEWS_AI_REGION: str | None = Field(default=None)
    PRAJNA_NEWS_MULTI_SOURCE_ENABLED: bool = Field(default=False)
    PRAJNA_NEWS_LIVE_STREAM_ENABLED: bool = Field(default=False)

    # ── validators ──────────────────────────────────────────────────────────
    @field_validator("PRAJNA_DATABASE_URL", "PRAJNA_TEST_DATABASE_URL")
    @classmethod
    def _reject_v1_database(cls, v: str) -> str:
        if not v:
            return v
        name = database_name(v)
        if name in FORBIDDEN_DATABASES:
            raise DatabaseIsolationError(
                f"DSN targets '{name}', which belongs to V1. V2 must never connect "
                f"to it. Point PRAJNA_DATABASE_URL at the 'prajna' database."
            )
        return v

    # ── derived ─────────────────────────────────────────────────────────────
    @property
    def archive_dir(self) -> pathlib.Path:
        p = pathlib.Path(self.PRAJNA_ARCHIVE_DIR)
        return p if p.is_absolute() else BACKEND_ROOT / p

    @property
    def log_dir(self) -> pathlib.Path:
        p = pathlib.Path(self.PRAJNA_LOG_DIR)
        return p if p.is_absolute() else BACKEND_ROOT / p

    @property
    def upstox_credentials_present(self) -> bool:
        """Credentials exist. Says NOTHING about whether a token is valid.

        V1 conflated these: `settings.upstox_authenticated` only checked that a
        token string was non-empty, so an expired token read as healthy and the
        integration went dark for hours with no alert. Token *validity* is a
        live probe, in app/vendor/upstox/auth.py.
        """
        return all(
            [self.UPSTOX_API_KEY, self.UPSTOX_API_SECRET,
             self.UPSTOX_TOTP_SECRET, self.UPSTOX_CLIENT_ID]
        )

    def require(self, *keys: str) -> None:
        """Assert specific keys are non-empty, naming every one that is not."""
        missing = [k for k in keys if not getattr(self, k, "")]
        if missing:
            raise ConfigError(f"required configuration missing: {', '.join(missing)}")


def database_name(dsn: str) -> str:
    """Database name from a DSN, ignoring driver prefix and query string."""
    tail = dsn.rsplit("/", 1)[-1] if "/" in dsn else ""
    return tail.split("?", 1)[0].strip()


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
