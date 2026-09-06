import os

from aliexpress_monitor.config import load_settings, parse_interval


def test_load_settings_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    monkeypatch.setenv("CHECK_INTERVAL", "2h")
    monkeypatch.setenv("SHIP_TO_COUNTRY", "de")
    monkeypatch.setenv("CURRENCY", "eur")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "db.sqlite"))
    monkeypatch.setenv("FETCH_MODE", "mock")
    monkeypatch.setenv("STATUS_PORT", "0")
    settings = load_settings(dotenv_path=None)
    assert settings.telegram_bot_token == "123:abc"
    assert settings.telegram_chat_id == "42"
    assert settings.check_interval_seconds == 2 * 3600
    assert settings.ship_to_country == "DE"
    assert settings.currency == "EUR"
    assert settings.fetch_mode == "mock"
    assert settings.status_port == 0


def test_interval_hours_default():
    assert parse_interval("") == 3 * 3600
    assert parse_interval("4h") == 4 * 3600
