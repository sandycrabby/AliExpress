import pytest

from aliexpress_monitor.auth import claim_or_reject, is_owner
from aliexpress_monitor.config import parse_interval
from aliexpress_monitor.formatting import (
    format_watch_list,
    parse_add_args,
    parse_id,
    parse_setrange_args,
)
from tests.conftest import make_settings


def test_parse_interval():
    assert parse_interval("3h") == 10800
    assert parse_interval("90m") == 5400
    assert parse_interval("120") == 120
    with pytest.raises(ValueError):
        parse_interval("nope")
    with pytest.raises(ValueError):
        parse_interval("5s")


def test_parse_add_args():
    parsed = parse_add_args(
        [
            "https://www.aliexpress.com/item/1005001234567890.html",
            "95",
            "Solar",
            "panel",
        ]
    )
    assert parsed.product_id == "1005001234567890"
    assert parsed.max_price == 95
    assert parsed.nickname == "Solar panel"

    parsed_id = parse_add_args(["1005001234567890", "40.5"])
    assert parsed_id.max_price == 40.5
    assert parsed_id.nickname is None

    with pytest.raises(ValueError):
        parse_add_args(["only-one"])
    with pytest.raises(ValueError):
        parse_add_args(["https://www.aliexpress.com/item/1005001234567890.html", "cheap"])


def test_parse_setrange_and_id():
    assert parse_setrange_args(["3", "10", "20"]) == (3, 10.0, 20.0)
    with pytest.raises(ValueError):
        parse_setrange_args(["3", "20", "10"])
    assert parse_id(["7"], "remove") == 7
    with pytest.raises(ValueError):
        parse_id(["nope"], "remove")


def test_format_empty_list():
    text = format_watch_list([])
    assert "No watches" in text


def test_owner_claim(db):
    settings = make_settings(database_path=db.path)
    allowed, msg = claim_or_reject(settings, db, 111)
    assert allowed
    assert "111" in msg
    assert is_owner(settings, db, 111)
    assert not is_owner(settings, db, 222)

    rejected, _ = claim_or_reject(settings, db, 222)
    assert not rejected

    locked = make_settings(database_path=db.path, telegram_chat_id="999")
    no, hint = claim_or_reject(locked, db, 111)
    assert not no
    assert "111" in hint
    yes, _ = claim_or_reject(locked, db, 999)
    assert yes
