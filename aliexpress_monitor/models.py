"""Plain data objects used across the app."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    return utc_now().replace(microsecond=0).isoformat()


@dataclass
class Watch:
    id: int
    product_id: str
    url: str
    nickname: str | None
    min_price: float | None
    max_price: float | None
    ship_to: str
    currency: str
    title: str | None
    last_price: float | None
    last_checked_at: str | None
    last_error: str | None
    last_alert_price: float | None
    last_alert_at: str | None
    alert_armed: bool
    created_at: str

    def display_name(self) -> str:
        return (self.nickname or self.title or f"Item {self.product_id}").strip()

    def target_label(self) -> str:
        if self.min_price is not None and self.max_price is not None:
            return f"{self.min_price:g}–{self.max_price:g}"
        if self.max_price is not None:
            return f"≤ {self.max_price:g}"
        if self.min_price is not None:
            return f"≥ {self.min_price:g}"
        return "no target"


@dataclass
class PricePoint:
    id: int
    watch_id: int
    price: float
    currency: str
    title: str | None
    fetched_at: str
    source: str


@dataclass
class FetchResult:
    ok: bool
    price: float | None = None
    currency: str | None = None
    title: str | None = None
    blocked: bool = False
    error: str | None = None
    source: str = "unknown"
    raw_debug: str | None = None

    @classmethod
    def success(
        cls,
        price: float,
        currency: str,
        title: str | None,
        source: str,
    ) -> FetchResult:
        return cls(
            ok=True,
            price=price,
            currency=currency,
            title=title,
            source=source,
        )

    @classmethod
    def failure(
        cls,
        error: str,
        *,
        blocked: bool = False,
        source: str = "unknown",
        raw_debug: str | None = None,
    ) -> FetchResult:
        return cls(
            ok=False,
            error=error,
            blocked=blocked,
            source=source,
            raw_debug=raw_debug,
        )


@dataclass
class CheckOutcome:
    watch: Watch
    fetch: FetchResult
    previous_price: float | None
    alerted: bool
    alert_reason: str | None
    rearmed: bool

    def as_summary(self) -> dict[str, Any]:
        return {
            "watch_id": self.watch.id,
            "name": self.watch.display_name(),
            "ok": self.fetch.ok,
            "price": self.fetch.price,
            "previous_price": self.previous_price,
            "alerted": self.alerted,
            "error": self.fetch.error,
        }
