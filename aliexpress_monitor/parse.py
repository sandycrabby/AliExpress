"""Extract a comparable product price from AliExpress HTML / JSON blobs."""

from __future__ import annotations

import json
import re
from typing import Any

# Block / anti-bot markers AliExpress serves with HTTP 200.
BLOCK_MARKERS = (
    "_____tmd_____/punish",
    "x5secdata",
    "Please slide to verify",
    "nc_1_wrapper",
    "baxia-punish",
    "captcha-title",
)

_PRICE_IN_TEXT = re.compile(
    r"(?:US\s*)?(?:USD|EUR|GBP|CAD|AUD|\$|€|£)\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{1,2})|[0-9]+(?:\.[0-9]{1,2}))",
    re.IGNORECASE,
)
_BARE_NUMBER = re.compile(r"([0-9]+(?:\.[0-9]{1,2}))")


def dig(node: Any, *path: Any, default: Any = None) -> Any:
    """Walk dict keys and list indexes; return default on any miss."""
    current = node
    for key in path:
        if isinstance(current, dict):
            current = current.get(key)
        elif isinstance(current, list):
            try:
                current = current[key]
            except (IndexError, TypeError):
                return default
        else:
            return default
        if current is None:
            return default
    return current


def is_blocked(html: str) -> bool:
    if not html:
        return True
    lowered = html.lower()
    if any(marker.lower() in lowered for marker in BLOCK_MARKERS):
        return True
    return False


def parse_money(value: Any) -> float | None:
    """Turn 12.99, 'US $12.99', '$1,299.00 - 1,499.00' into a float (low end)."""
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = float(value)
        return number if number > 0 else None
    text = str(value).strip()
    if not text:
        return None
    # Range: use the lowest listed price so "on sale from" is comparable.
    first_span = text.split("-", 1)[0]
    match = _PRICE_IN_TEXT.search(first_span) or _PRICE_IN_TEXT.search(text)
    if match:
        return float(match.group(1).replace(",", ""))
    match = _BARE_NUMBER.search(first_span.replace(",", ""))
    if match:
        number = float(match.group(1))
        return number if number > 0 else None
    return None


def _first_price(*candidates: Any) -> float | None:
    for candidate in candidates:
        parsed = parse_money(candidate)
        if parsed is not None:
            return parsed
    return None


def extract_from_run_params(data: dict[str, Any]) -> dict[str, Any] | None:
    """Classic window.runParams.data shape plus a few newer aliases."""
    if not isinstance(data, dict):
        return None
    payload = data.get("data") if isinstance(data.get("data"), dict) else data

    title = (
        dig(payload, "titleModule", "subject")
        or dig(payload, "productInfoComponent", "subject")
        or dig(payload, "metaDataComponent", "title")
        or dig(payload, "title")
    )

    currency = (
        dig(payload, "currencyModule", "currencyCode")
        or dig(payload, "currencyCode")
        or dig(payload, "priceModule", "minAmount", "currency")
        or dig(payload, "priceModule", "minActivityAmount", "currency")
    )

    price = _first_price(
        dig(payload, "priceModule", "minActivityAmount", "value"),
        dig(payload, "priceModule", "minAmount", "value"),
        dig(payload, "priceModule", "formatedActivityPrice"),
        dig(payload, "priceModule", "formatedPrice"),
        dig(payload, "priceComponent", "discountPrice", "minPrice"),
        dig(payload, "priceComponent", "origPrice", "minPrice"),
        dig(payload, "salePrice", "min", "value"),
        dig(payload, "salePrice", "value"),
        dig(payload, "originalPrice", "min", "value"),
    )

    if price is None:
        sku_list = dig(payload, "skuModule", "skuPriceList", default=[]) or []
        sku_prices: list[float] = []
        for sku in sku_list:
            val = sku.get("skuVal", {}) if isinstance(sku, dict) else {}
            found = _first_price(
                dig(val, "skuActivityAmount", "value"),
                dig(val, "skuAmount", "value"),
            )
            if found is not None:
                sku_prices.append(found)
        if sku_prices:
            price = min(sku_prices)

    if price is None:
        return None
    return {"price": price, "currency": currency, "title": title}


def _extract_json_object(text: str, start: int) -> dict[str, Any] | None:
    """Parse the `{...}` object that starts at `start` (brace-balanced)."""
    if start < 0 or start >= len(text) or text[start] != "{":
        return None
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    parsed = json.loads(text[start : index + 1])
                except json.JSONDecodeError:
                    return None
                return parsed if isinstance(parsed, dict) else None
    return None


def extract_run_params_json(html: str) -> dict[str, Any] | None:
    """Pull window.runParams JSON out of raw HTML when JS eval is unavailable."""
    if not html:
        return None
    markers = ("window.runParams", "runParams")
    for marker in markers:
        pos = 0
        while True:
            found = html.find(marker, pos)
            if found < 0:
                break
            brace = html.find("{", found)
            if brace < 0:
                break
            parsed = _extract_json_object(html, brace)
            if parsed:
                return parsed
            pos = found + len(marker)
    data_mark = re.search(r"\bdata\s*:\s*\{", html)
    if data_mark:
        brace = html.find("{", data_mark.start())
        parsed = _extract_json_object(html, brace)
        if parsed:
            return parsed
    return None


def extract_json_ld(html: str) -> dict[str, Any] | None:
    if not html:
        return None
    for match in re.finditer(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html,
        re.DOTALL | re.IGNORECASE,
    ):
        try:
            data = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            if not isinstance(item, dict):
                continue
            offers = item.get("offers")
            offer_list = offers if isinstance(offers, list) else [offers]
            for offer in offer_list:
                if not isinstance(offer, dict):
                    continue
                price = parse_money(offer.get("lowPrice") or offer.get("price"))
                if price is None:
                    continue
                return {
                    "price": price,
                    "currency": offer.get("priceCurrency"),
                    "title": item.get("name"),
                }
    return None


def extract_from_selectors_text(texts: list[str]) -> float | None:
    for text in texts:
        price = parse_money(text)
        if price is not None:
            return price
    return None


def extract_price_from_html(html: str) -> dict[str, Any] | None:
    """Best-effort parse of a full product page (no browser needed)."""
    if is_blocked(html) and "runParams" not in html:
        return None
    data = extract_run_params_json(html)
    if data:
        parsed = extract_from_run_params(data)
        if parsed:
            return parsed
    return extract_json_ld(html)
