"""Load settings from environment variables (and an optional .env file)."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

_INTERVAL_RE = re.compile(
    r"^\s*(\d+(?:\.\d+)?)\s*(h|hr|hrs|hour|hours|m|min|mins|minute|minutes|s|sec|secs|second|seconds)?\s*$",
    re.IGNORECASE,
)


def parse_interval(value: str, default_seconds: int = 3 * 3600) -> int:
    """Parse '3h', '90m', '10800' into seconds."""
    if value is None or str(value).strip() == "":
        return default_seconds
    match = _INTERVAL_RE.match(str(value))
    if not match:
        raise ValueError(
            f"Invalid CHECK_INTERVAL {value!r}. Use e.g. 3h, 90m, or 10800."
        )
    amount = float(match.group(1))
    unit = (match.group(2) or "s").lower()
    if unit.startswith("h"):
        seconds = amount * 3600
    elif unit.startswith("m"):
        seconds = amount * 60
    else:
        seconds = amount
    if seconds < 30:
        raise ValueError("CHECK_INTERVAL must be at least 30 seconds.")
    return int(seconds)


def _env(name: str, default: str = "") -> str:
    raw = os.environ.get(name, default)
    return raw.strip() if raw is not None else default


def _env_bool(name: str, default: bool) -> bool:
    raw = _env(name, "true" if default else "false").lower()
    return raw in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    raw = _env(name, "")
    return float(raw) if raw else default


def _env_int(name: str, default: int) -> int:
    raw = _env(name, "")
    return int(raw) if raw else default


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    telegram_chat_id: str
    check_interval_seconds: int
    ship_to_country: str
    currency: str
    database_path: Path
    fetch_mode: str
    mock_prices_path: Path
    alert_drop_percent: float
    alert_drop_abs: float
    check_delay_seconds: float
    status_host: str
    status_port: int
    playwright_headless: bool
    navigation_timeout_ms: int

    @property
    def uses_playwright(self) -> bool:
        return self.fetch_mode == "playwright"


def load_settings(dotenv_path: str | Path | None = ".env") -> Settings:
    """Read .env (if present) then environment variables."""
    if dotenv_path:
        load_dotenv(dotenv_path, override=False)

    fetch_mode = _env("FETCH_MODE", "playwright").lower()
    if fetch_mode not in {"playwright", "mock"}:
        raise ValueError("FETCH_MODE must be 'playwright' or 'mock'.")

    country = _env("SHIP_TO_COUNTRY", "US").upper()
    if len(country) != 2 or not country.isalpha():
        raise ValueError("SHIP_TO_COUNTRY must be a 2-letter country code, e.g. US.")

    return Settings(
        telegram_bot_token=_env("TELEGRAM_BOT_TOKEN"),
        telegram_chat_id=_env("TELEGRAM_CHAT_ID"),
        check_interval_seconds=parse_interval(_env("CHECK_INTERVAL", "3h")),
        ship_to_country=country,
        currency=_env("CURRENCY", "USD").upper(),
        database_path=Path(_env("DATABASE_PATH", "./data/monitor.db")),
        fetch_mode=fetch_mode,
        mock_prices_path=Path(
            _env("MOCK_PRICES_PATH", "./tests/fixtures/mock_prices.json")
        ),
        alert_drop_percent=_env_float("ALERT_DROP_PERCENT", 2.0),
        alert_drop_abs=_env_float("ALERT_DROP_ABS", 1.0),
        check_delay_seconds=_env_float("CHECK_DELAY_SECONDS", 4.0),
        status_host=_env("STATUS_HOST", "0.0.0.0"),
        status_port=_env_int("STATUS_PORT", 8080),
        playwright_headless=_env_bool("PLAYWRIGHT_HEADLESS", True),
        navigation_timeout_ms=_env_int("NAVIGATION_TIMEOUT_MS", 45000),
    )
