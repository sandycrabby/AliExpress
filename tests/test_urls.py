import pytest

from aliexpress_monitor.urls import (
    UrlParseError,
    canonical_url,
    extract_product_id,
    fetch_url,
    fetch_url_candidates,
    looks_like_aliexpress,
)


def test_extract_from_standard_url():
    assert (
        extract_product_id("https://www.aliexpress.com/item/1005001234567890.html")
        == "1005001234567890"
    )


def test_extract_from_us_url_and_bare_id():
    assert (
        extract_product_id("https://www.aliexpress.us/item/3256801234567890.html")
        == "3256801234567890"
    )
    assert extract_product_id("1005001234567890") == "1005001234567890"


def test_extract_rejects_garbage():
    with pytest.raises(UrlParseError):
        extract_product_id("https://example.com/not-a-product")


def test_canonical_and_fetch_url_keep_host_and_pin_shipto():
    original = "https://www.aliexpress.us/item/1005001234567890.html"
    product_id = extract_product_id(original)
    assert canonical_url(product_id, original).endswith("/item/1005001234567890.html")
    us = fetch_url(product_id, "US", original)
    assert "aliexpress.us" in us
    de = fetch_url(product_id, "DE", original)
    assert "_randl_shipto=DE" in de


def test_fetch_url_candidates_add_us_fallback():
    urls = fetch_url_candidates("1005001234567890", "US")
    assert any("aliexpress.com" in u for u in urls)
    assert any("aliexpress.us" in u for u in urls)
    us_only = fetch_url_candidates(
        "1005001234567890",
        "US",
        "https://www.aliexpress.us/item/1005001234567890.html",
    )
    assert len(us_only) == 1
    assert "aliexpress.us" in us_only[0]


def test_looks_like_aliexpress():
    assert looks_like_aliexpress("https://www.aliexpress.com/item/1005001.html")
    assert looks_like_aliexpress("1005001234567890")
    assert not looks_like_aliexpress("https://amazon.com/dp/123")
