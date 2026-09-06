"""User-facing Telegram / CLI text. Keep handlers thin."""

from __future__ import annotations

import re
from dataclasses import dataclass

from aliexpress_monitor.models import CheckOutcome, PricePoint, Watch
from aliexpress_monitor.urls import UrlParseError, canonical_url, extract_product_id

CURRENCY_SYMBOLS = {
    "USD": "$",
    "EUR": "€",
    "GBP": "£",
    "CAD": "CA$",
    "AUD": "A$",
}

HELP_TEXT = """\
AliExpress price monitor

Add a watch
  /add <url-or-id> <max_price> [nickname]
  Example: /add https://www.aliexpress.com/item/1005001234567890.html 95 Solar panel

Manage
  /list                  Your watches
  /remove <id>           Stop watching
  /setrange <id> <min> <max>
  /reset <id>            Allow the next in-range price to alert again
  /history <id>          Recent prices
  /check                 Check every watch now
  /check <id>            Check one watch now
  /whoami                Show this chat's numeric id

Alerts fire when a price enters your target (at or below max, and at or
above min if you set a range). You will not get a repeat alert on every
check. A new alert is sent if the price leaves the range and comes back,
drops further in a meaningful way, or you /reset the watch.
"""

START_TEXT = """\
I'll watch AliExpress listings and message you when a price hits your target.

Paste a product link and a max price:

  /add https://www.aliexpress.com/item/1005001234567890.html 95

Send /help for every command.
"""


@dataclass
class AddArgs:
    product_id: str
    url: str
    max_price: float
    nickname: str | None


def money(amount: float | None, currency: str = "USD") -> str:
    if amount is None:
        return "—"
    symbol = CURRENCY_SYMBOLS.get(currency.upper(), "")
    if symbol:
        return f"{symbol}{amount:,.2f}"
    return f"{amount:,.2f} {currency}"


def _parse_price(token: str) -> float:
    cleaned = token.strip().replace(",", "").replace("$", "")
    value = float(cleaned)
    if value < 0:
        raise ValueError("Price cannot be negative.")
    return value


def parse_add_args(args: list[str]) -> AddArgs:
    if len(args) < 2:
        raise ValueError(
            "Usage: /add <url-or-id> <max_price> [nickname]\n"
            "Example: /add https://www.aliexpress.com/item/1005001234567890.html 95 Solar panel"
        )
    raw_id = args[0]
    try:
        product_id = extract_product_id(raw_id)
    except UrlParseError as exc:
        raise ValueError(str(exc)) from exc
    try:
        max_price = _parse_price(args[1])
    except ValueError as exc:
        raise ValueError(f"Max price must be a number, got {args[1]!r}.") from exc
    nickname = " ".join(args[2:]).strip() or None
    url = canonical_url(product_id, raw_id if "http" in raw_id else None)
    return AddArgs(
        product_id=product_id,
        url=url,
        max_price=max_price,
        nickname=nickname,
    )


def parse_id(args: list[str], command: str) -> int:
    if not args:
        raise ValueError(f"Usage: /{command} <id>")
    if not re.fullmatch(r"\d+", args[0]):
        raise ValueError(f"Watch id must be a number, got {args[0]!r}.")
    return int(args[0])


def parse_setrange_args(args: list[str]) -> tuple[int, float, float]:
    if len(args) < 3:
        raise ValueError("Usage: /setrange <id> <min> <max>")
    watch_id = parse_id(args[:1], "setrange")
    try:
        min_price = _parse_price(args[1])
        max_price = _parse_price(args[2])
    except ValueError as exc:
        raise ValueError("Min and max must be numbers.") from exc
    if min_price > max_price:
        raise ValueError("Min price cannot be greater than max price.")
    return watch_id, min_price, max_price


def format_watch_line(watch: Watch) -> str:
    last = money(watch.last_price, watch.currency)
    extra = ""
    if watch.last_error:
        extra = f"\n   last error: {watch.last_error}"
    checked = watch.last_checked_at or "never"
    return (
        f"#{watch.id} {watch.display_name()}\n"
        f"   {last}  ·  target {watch.target_label()}  ·  {watch.ship_to}/{watch.currency}\n"
        f"   last check: {checked}{extra}\n"
        f"   {watch.url}"
    )


def format_watch_list(watches: list[Watch]) -> str:
    if not watches:
        return "No watches yet. Add one with /add <url> <max_price>."
    header = f"Your watches ({len(watches)}):"
    return header + "\n\n" + "\n\n".join(format_watch_line(w) for w in watches)


def format_alert(outcome: CheckOutcome) -> str:
    watch = outcome.watch
    currency = outcome.fetch.currency or watch.currency
    previous = ""
    if outcome.previous_price is not None:
        previous = f"\nPrevious: {money(outcome.previous_price, currency)}"
    reason = (
        "Price dropped further after the last alert."
        if outcome.alert_reason == "further_drop"
        else "Price is inside your target."
    )
    return (
        f"Price alert: {watch.display_name()}\n\n"
        f"{reason}\n"
        f"Current: {money(outcome.fetch.price, currency)}"
        f"{previous}\n"
        f"Target: {watch.target_label()}\n\n"
        f"{watch.url}"
    )


def format_check_report(outcomes: list[CheckOutcome]) -> str:
    if not outcomes:
        return "No watches to check. Add one with /add <url> <max_price>."
    lines = ["Check results:"]
    for outcome in outcomes:
        watch = outcome.watch
        if outcome.fetch.ok:
            currency = outcome.fetch.currency or watch.currency
            prev = ""
            if outcome.previous_price is not None:
                prev = f" (was {money(outcome.previous_price, currency)})"
            flag = " ALERT" if outcome.alerted else ""
            lines.append(
                f"#{watch.id} {watch.display_name()}: "
                f"{money(outcome.fetch.price, currency)}{prev}{flag}"
            )
        else:
            lines.append(
                f"#{watch.id} {watch.display_name()}: failed — {outcome.fetch.error}"
            )
    return "\n".join(lines)


def format_history(watch: Watch, points: list[PricePoint]) -> str:
    if not points:
        return f"#{watch.id} {watch.display_name()}: no history yet. Run /check."
    lines = [f"Recent prices for #{watch.id} {watch.display_name()}:"]
    for point in points:
        lines.append(f"  {point.fetched_at}  {money(point.price, point.currency)}")
    return "\n".join(lines)
