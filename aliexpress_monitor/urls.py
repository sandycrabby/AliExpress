"""Parse AliExpress product URLs and product IDs."""

from __future__ import annotations

import re
from urllib.parse import urlparse

# Typical AliExpress item ids are 10–16 digits (older ids can be shorter).
_ITEM_PATH_RE = re.compile(
    r"(?:/item/|/i/|/item//)(\d{8,20})(?:\.html)?",
    re.IGNORECASE,
)
_BARE_ID_RE = re.compile(r"^\d{8,20}$")
_HOST_RE = re.compile(r"(^|\.)aliexpress\.", re.IGNORECASE)


class UrlParseError(ValueError):
    pass


def extract_product_id(value: str) -> str:
    """Return the numeric product id from a URL, path, or bare id."""
    text = (value or "").strip()
    if not text:
        raise UrlParseError("Please provide an AliExpress product URL or product ID.")

    if _BARE_ID_RE.fullmatch(text):
        return text

    match = _ITEM_PATH_RE.search(text)
    if match:
        return match.group(1)

    raise UrlParseError(
        "Could not find a product ID. Paste a link like "
        "https://www.aliexpress.com/item/1005001234567890.html "
        "or the numeric product ID."
    )


def canonical_url(product_id: str, original: str | None = None) -> str:
    """Prefer the user's original AliExpress host; otherwise use .com."""
    if original:
        parsed = urlparse(original.strip())
        if parsed.scheme in {"http", "https"} and parsed.netloc and _HOST_RE.search(
            parsed.netloc
        ):
            return f"{parsed.scheme}://{parsed.netloc}/item/{product_id}.html"
    return f"https://www.aliexpress.com/item/{product_id}.html"


def fetch_url(product_id: str, ship_to: str, original: str | None = None) -> str:
    """Build the URL we open in the browser, pinning ship-to when possible."""
    base = canonical_url(product_id, original)
    country = (ship_to or "US").upper()
    parsed = urlparse(base)
    host = parsed.netloc.lower()
    if host.endswith("aliexpress.us") and country == "US":
        return base
    return f"{base}?gatewayAdapt=glo2usa&_randl_shipto={country}"


def looks_like_aliexpress(value: str) -> bool:
    text = (value or "").strip()
    if _BARE_ID_RE.fullmatch(text):
        return True
    parsed = urlparse(text if "://" in text else f"https://{text}")
    return bool(_HOST_RE.search(parsed.netloc)) or bool(_ITEM_PATH_RE.search(text))
