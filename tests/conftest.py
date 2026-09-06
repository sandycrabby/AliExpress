from __future__ import annotations

from pathlib import Path

import pytest

from aliexpress_monitor.checker import Checker
from aliexpress_monitor.config import Settings
from aliexpress_monitor.db import Database
from aliexpress_monitor.fetchers import MockFetcher

FIXTURES = Path(__file__).parent / "fixtures"


def make_settings(**overrides) -> Settings:
    values = dict(
        telegram_bot_token="",
        telegram_chat_id="",
        check_interval_seconds=10800,
        ship_to_country="US",
        currency="USD",
        database_path=Path(":memory:"),
        fetch_mode="mock",
        mock_prices_path=FIXTURES / "mock_prices.json",
        alert_drop_percent=2.0,
        alert_drop_abs=1.0,
        check_delay_seconds=0,
        status_host="127.0.0.1",
        status_port=0,
        playwright_headless=True,
        navigation_timeout_ms=5000,
    )
    values.update(overrides)
    return Settings(**values)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return make_settings(database_path=tmp_path / "monitor.db")


@pytest.fixture
def db(settings: Settings) -> Database:
    database = Database(settings.database_path)
    database.init()
    yield database
    database.close()


@pytest.fixture
def fetcher() -> MockFetcher:
    return MockFetcher(
        prices={
            "1005001111111111": {
                "price": 89.5,
                "title": "200W Solar Panel Kit",
                "currency": "USD",
            },
            "1005002222222222": {
                "price": 129.0,
                "title": "12V 100Ah LiFePO4 Battery",
                "currency": "USD",
            },
        }
    )


@pytest.fixture
def checker(settings: Settings, db: Database, fetcher: MockFetcher) -> Checker:
    return Checker(db, fetcher, settings)
