"""Decide when a price should trigger a Telegram alert (anti-spam)."""

from __future__ import annotations

from dataclasses import dataclass

from aliexpress_monitor.models import Watch


@dataclass(frozen=True)
class AlertDecision:
    in_range: bool
    should_alert: bool
    reason: str | None
    rearm: bool


def price_in_range(
    price: float,
    min_price: float | None,
    max_price: float | None,
) -> bool:
    if min_price is None and max_price is None:
        return False
    if min_price is not None and price < min_price:
        return False
    if max_price is not None and price > max_price:
        return False
    return True


def meaningful_drop(
    last_alert_price: float,
    current_price: float,
    drop_percent: float,
    drop_abs: float,
) -> bool:
    drop = last_alert_price - current_price
    if drop <= 0:
        return False
    if drop >= drop_abs:
        return True
    if last_alert_price > 0 and (drop / last_alert_price) * 100 >= drop_percent:
        return True
    return False


def decide_alert(
    watch: Watch,
    current_price: float,
    *,
    drop_percent: float = 2.0,
    drop_abs: float = 1.0,
) -> AlertDecision:
    """Alert once when the price enters the target, then only on a further drop.

    After an alert we disarm. We re-arm when the price leaves the target range
    so the next crossing fires again. `/reset` also re-arms.
    """
    in_range = price_in_range(current_price, watch.min_price, watch.max_price)

    if not in_range:
        return AlertDecision(
            in_range=False,
            should_alert=False,
            reason=None,
            rearm=not watch.alert_armed,
        )

    if watch.alert_armed:
        return AlertDecision(
            in_range=True,
            should_alert=True,
            reason="entered_range",
            rearm=False,
        )

    if watch.last_alert_price is not None and meaningful_drop(
        watch.last_alert_price,
        current_price,
        drop_percent,
        drop_abs,
    ):
        return AlertDecision(
            in_range=True,
            should_alert=True,
            reason="further_drop",
            rearm=False,
        )

    return AlertDecision(
        in_range=True,
        should_alert=False,
        reason=None,
        rearm=False,
    )
