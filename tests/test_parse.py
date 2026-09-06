from pathlib import Path

from aliexpress_monitor.parse import (
    extract_from_run_params,
    extract_price_from_html,
    is_blocked,
    parse_money,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_money_formats():
    assert parse_money("US $89.50") == 89.5
    assert parse_money("$1,299.00 - 1,499.00") == 1299.0
    assert parse_money(45) == 45.0
    assert parse_money(None) is None


def test_extract_run_params_classic_shape():
    data = {
        "titleModule": {"subject": "Battery"},
        "priceModule": {
            "minActivityAmount": {"value": 119.0, "currency": "USD"},
            "formatedActivityPrice": "US $119.00",
        },
        "currencyModule": {"currencyCode": "USD"},
    }
    parsed = extract_from_run_params(data)
    assert parsed["price"] == 119.0
    assert parsed["title"] == "Battery"
    assert parsed["currency"] == "USD"


def test_extract_sku_min_price():
    data = {
        "titleModule": {"subject": "Panel"},
        "skuModule": {
            "skuPriceList": [
                {"skuVal": {"skuAmount": {"value": 80}}},
                {"skuVal": {"skuActivityAmount": {"value": 70}}},
            ]
        },
    }
    assert extract_from_run_params(data)["price"] == 70


def test_html_fixture_and_blocked_page():
    html = (FIXTURES / "product_page.html").read_text(encoding="utf-8")
    parsed = extract_price_from_html(html)
    assert parsed is not None
    assert parsed["price"] == 89.5
    assert "Solar" in parsed["title"]

    blocked = (FIXTURES / "blocked_page.html").read_text(encoding="utf-8")
    assert is_blocked(blocked)
    assert extract_price_from_html(blocked) is None
