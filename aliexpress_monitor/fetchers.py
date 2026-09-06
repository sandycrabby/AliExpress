"""Price fetchers: Playwright (live) and mock (CI / local fixtures)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Protocol

from aliexpress_monitor.models import FetchResult
from aliexpress_monitor.parse import (
    extract_from_run_params,
    extract_json_ld,
    extract_price_from_html,
    extract_run_params_json,
    is_blocked,
    parse_money,
)
from aliexpress_monitor.urls import fetch_url_candidates

logger = logging.getLogger(__name__)

# Common live-page price nodes. AliExpress rotates class names; keep several.
PRICE_SELECTORS = [
    "[data-pl='product-price']",
    ".product-price-value",
    "span.price--currentPriceText--V8_Y5_b",
    ".uniform-banner-box-price",
    "[class*='price--current']",
    "[class*='Price-module']",
]


class PriceFetcher(Protocol):
    async def fetch(
        self,
        *,
        product_id: str,
        url: str,
        ship_to: str,
        currency: str,
    ) -> FetchResult: ...

    async def close(self) -> None: ...


class MockFetcher:
    """Read prices from a JSON fixture. Never talks to AliExpress."""

    def __init__(self, path: str | Path | None = None, prices: dict | None = None) -> None:
        self.path = Path(path) if path else None
        self._inline = prices

    def _load(self) -> dict[str, Any]:
        if self._inline is not None:
            return self._inline
        if not self.path or not self.path.exists():
            raise FileNotFoundError(
                f"Mock prices file not found: {self.path}. "
                "Set MOCK_PRICES_PATH or FETCH_MODE=playwright."
            )
        return json.loads(self.path.read_text(encoding="utf-8"))

    def set_price(self, product_id: str, price: float, title: str | None = None) -> None:
        data = self._load()
        entry = data.get(product_id)
        if isinstance(entry, dict):
            entry["price"] = price
            if title:
                entry["title"] = title
        else:
            data[product_id] = {"price": price, "title": title or f"Mock item {product_id}"}
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        else:
            self._inline = data

    async def fetch(
        self,
        *,
        product_id: str,
        url: str,
        ship_to: str,
        currency: str,
    ) -> FetchResult:
        try:
            data = self._load()
        except Exception as exc:  # noqa: BLE001 — surface fixture errors to Telegram
            return FetchResult.failure(str(exc), source="mock")

        if product_id not in data:
            return FetchResult.failure(
                f"No mock price for product {product_id}. "
                f"Add it to {self.path or 'inline fixture'}.",
                source="mock",
            )
        entry = data[product_id]
        if isinstance(entry, (int, float)):
            price = float(entry)
            title = f"Mock item {product_id}"
            entry_currency = currency
        elif isinstance(entry, dict):
            if entry.get("error"):
                return FetchResult.failure(str(entry["error"]), source="mock")
            price = parse_money(entry.get("price"))
            if price is None:
                return FetchResult.failure("Mock entry is missing a price.", source="mock")
            title = entry.get("title") or f"Mock item {product_id}"
            entry_currency = entry.get("currency") or currency
        else:
            return FetchResult.failure("Invalid mock price entry.", source="mock")
        return FetchResult.success(price, entry_currency, title, source="mock")

    async def close(self) -> None:
        return None


class PlaywrightFetcher:
    """Open the product page in headless Chromium with a pinned ship-to cookie."""

    def __init__(
        self,
        *,
        headless: bool = True,
        timeout_ms: int = 45000,
    ) -> None:
        self.headless = headless
        self.timeout_ms = timeout_ms
        self._playwright = None
        self._browser = None

    async def _ensure_browser(self):
        if self._browser is not None:
            return
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "Playwright is not installed. Run: pip install playwright && "
                "playwright install chromium"
            ) from exc
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self.headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )

    async def close(self) -> None:
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None

    def _cookie(self, ship_to: str, currency: str) -> dict[str, str]:
        country = (ship_to or "US").upper()
        cur = (currency or "USD").upper()
        return {
            "name": "aep_usuc_f",
            "value": f"b_locale=en_US&c_tp={cur}&region={country}&site=glo",
            "domain": ".aliexpress.com",
            "path": "/",
        }

    async def fetch(
        self,
        *,
        product_id: str,
        url: str,
        ship_to: str,
        currency: str,
    ) -> FetchResult:
        try:
            await self._ensure_browser()
        except Exception as exc:  # noqa: BLE001
            return FetchResult.failure(f"Could not start browser: {exc}", source="playwright")

        last_failure: FetchResult | None = None
        for target in fetch_url_candidates(product_id, ship_to, url):
            result = await self._fetch_one(target, ship_to, currency)
            if result.ok:
                return result
            last_failure = result
            if result.blocked:
                logger.info("Blocked on %s; trying next candidate if any", target)
                continue
            break
        return last_failure or FetchResult.failure(
            "No price could be fetched.", source="playwright"
        )

    async def _fetch_one(self, target: str, ship_to: str, currency: str) -> FetchResult:
        context = None
        try:
            context = await self._browser.new_context(
                locale="en-US",
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/192.168.1.5 Safari/537.36"
                ),
                extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
            )
            await context.add_cookies(
                [
                    self._cookie(ship_to, currency),
                    {**self._cookie(ship_to, currency), "domain": ".aliexpress.us"},
                ]
            )
            page = await context.new_page()
            logger.info("Opening %s (ship-to %s/%s)", target, ship_to, currency)
            response = await page.goto(
                target,
                wait_until="domcontentloaded",
                timeout=self.timeout_ms,
            )
            # Give client-side price modules a moment to land.
            try:
                await page.wait_for_timeout(2500)
            except Exception:  # noqa: BLE001
                pass

            html = await page.content()
            if response is not None and response.status >= 400:
                return FetchResult.failure(
                    f"AliExpress returned HTTP {response.status}.",
                    source="playwright",
                )
            if is_blocked(html) and "runParams" not in html:
                return FetchResult.failure(
                    "AliExpress served an anti-bot / captcha page. "
                    "Try again later from a home/residential network.",
                    blocked=True,
                    source="playwright",
                )

            extracted = await self._extract(page, html)
            if extracted is None:
                return FetchResult.failure(
                    "Loaded the page but could not find a price. "
                    "The listing may be gone, or AliExpress changed the layout.",
                    source="playwright",
                    raw_debug=_debug_snippet(html),
                )
            return FetchResult.success(
                price=extracted["price"],
                currency=extracted.get("currency") or currency,
                title=extracted.get("title"),
                source="playwright",
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Playwright fetch failed for %s", target)
            return FetchResult.failure(f"Browser fetch failed: {exc}", source="playwright")
        finally:
            if context is not None:
                await context.close()

    async def _extract(self, page, html: str) -> dict[str, Any] | None:
        # 1. Live JS state (most reliable when the page actually rendered).
        try:
            run_params = await page.evaluate(
                """() => {
                    if (window.runParams && window.runParams.data) {
                        return window.runParams.data;
                    }
                    if (window.runParams) return window.runParams;
                    return null;
                }"""
            )
            parsed = extract_from_run_params(run_params) if run_params else None
            if parsed:
                return parsed
        except Exception:  # noqa: BLE001
            logger.debug("window.runParams eval failed", exc_info=True)

        # 2. HTML / JSON-LD fallbacks (SSR pages, partial renders).
        parsed = extract_price_from_html(html)
        if parsed:
            return parsed
        data = extract_run_params_json(html)
        if data:
            parsed = extract_from_run_params(data)
            if parsed:
                return parsed
        parsed = extract_json_ld(html)
        if parsed:
            return parsed

        # 3. Visible price nodes as a last resort.
        texts: list[str] = []
        for selector in PRICE_SELECTORS:
            try:
                loc = page.locator(selector).first
                if await loc.count() == 0:
                    continue
                text = (await loc.inner_text()).strip()
                if text:
                    texts.append(text)
            except Exception:  # noqa: BLE001
                continue
        for text in texts:
            price = parse_money(text)
            if price is not None:
                title = None
                try:
                    title = await page.title()
                except Exception:  # noqa: BLE001
                    title = None
                return {"price": price, "currency": None, "title": title}

        return None


def build_fetcher(settings) -> PriceFetcher:
    if settings.fetch_mode == "mock":
        return MockFetcher(settings.mock_prices_path)
    return PlaywrightFetcher(
        headless=settings.playwright_headless,
        timeout_ms=settings.navigation_timeout_ms,
    )


def _debug_snippet(html: str, limit: int = 400) -> str:
    compact = " ".join((html or "").split())
    return compact[:limit]
