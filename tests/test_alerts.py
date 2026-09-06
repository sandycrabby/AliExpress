from aliexpress_monitor.alerts import decide_alert, meaningful_drop, price_in_range
from aliexpress_monitor.models import Watch


def _watch(**overrides) -> Watch:
    data = dict(
        id=1,
        product_id="1",
        url="https://www.aliexpress.com/item/1.html",
        nickname="Panel",
        min_price=None,
        max_price=100.0,
        ship_to="US",
        currency="USD",
        title="Panel",
        last_price=120.0,
        last_checked_at=None,
        last_error=None,
        last_alert_price=None,
        last_alert_at=None,
        alert_armed=True,
        created_at="2026-01-01T00:00:00+00:00",
    )
    data.update(overrides)
    return Watch(**data)


def test_price_in_range_max_only():
    assert price_in_range(99, None, 100)
    assert price_in_range(100, None, 100)
    assert not price_in_range(101, None, 100)


def test_price_in_range_band():
    assert price_in_range(50, 40, 80)
    assert not price_in_range(39, 40, 80)
    assert not price_in_range(81, 40, 80)


def test_alert_on_first_crossing():
    decision = decide_alert(_watch(alert_armed=True), 90)
    assert decision.should_alert
    assert decision.reason == "entered_range"
    assert decision.in_range


def test_no_repeat_alert_while_still_in_range():
    decision = decide_alert(
        _watch(alert_armed=False, last_alert_price=90),
        89.5,
    )
    assert not decision.should_alert
    assert decision.in_range


def test_further_drop_realerts():
    decision = decide_alert(
        _watch(alert_armed=False, last_alert_price=90),
        85,
        drop_percent=2,
        drop_abs=1,
    )
    assert decision.should_alert
    assert decision.reason == "further_drop"


def test_tiny_drop_does_not_realert():
    decision = decide_alert(
        _watch(alert_armed=False, last_alert_price=90),
        89.8,
        drop_percent=2,
        drop_abs=1,
    )
    assert not decision.should_alert


def test_leaving_range_rearms():
    decision = decide_alert(_watch(alert_armed=False, last_alert_price=90), 140)
    assert not decision.should_alert
    assert not decision.in_range
    assert decision.rearm


def test_meaningful_drop_percent_and_abs():
    assert meaningful_drop(100, 97, drop_percent=2, drop_abs=10)
    assert meaningful_drop(100, 98.5, drop_percent=5, drop_abs=1)
    assert not meaningful_drop(100, 99.5, drop_percent=2, drop_abs=1)
    assert not meaningful_drop(100, 101, drop_percent=2, drop_abs=1)
