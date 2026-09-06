import pytest

from aliexpress_monitor.formatting import format_alert, format_check_report


@pytest.mark.asyncio
async def test_check_alerts_when_price_hits_max(db, checker, fetcher):
    watch = db.add_watch(
        product_id="1005001111111111",
        url="https://www.aliexpress.com/item/1005001111111111.html",
        nickname="Solar panel",
        min_price=None,
        max_price=95,
        ship_to="US",
        currency="USD",
    )
    outcomes = await checker.check_all()
    assert len(outcomes) == 1
    assert outcomes[0].fetch.ok
    assert outcomes[0].fetch.price == 89.5
    assert outcomes[0].alerted
    stored = db.get_watch(watch.id)
    assert stored.last_price == 89.5
    assert stored.alert_armed is False
    assert stored.title == "200W Solar Panel Kit"
    assert len(db.history(watch.id)) == 1

    second = await checker.check_all()
    assert second[0].fetch.ok
    assert second[0].alerted is False
    assert len(db.history(watch.id)) == 2


@pytest.mark.asyncio
async def test_further_drop_alerts_again(db, checker, fetcher):
    db.add_watch(
        product_id="1005001111111111",
        url="https://www.aliexpress.com/item/1005001111111111.html",
        nickname="Solar panel",
        min_price=None,
        max_price=95,
        ship_to="US",
        currency="USD",
    )
    first = await checker.check_all()
    assert first[0].alerted

    fetcher.set_price("1005001111111111", 80.0)
    second = await checker.check_all()
    assert second[0].alerted
    assert second[0].alert_reason == "further_drop"
    assert "80.00" in format_alert(second[0])
    assert "Previous" in format_alert(second[0])


@pytest.mark.asyncio
async def test_out_of_range_then_back_in_alerts(db, checker, fetcher):
    db.add_watch(
        product_id="1005001111111111",
        url="https://www.aliexpress.com/item/1005001111111111.html",
        nickname="Solar panel",
        min_price=None,
        max_price=95,
        ship_to="US",
        currency="USD",
    )
    await checker.check_all()
    fetcher.set_price("1005001111111111", 140.0)
    mid = await checker.check_all()
    assert mid[0].alerted is False
    assert db.get_watch(1).alert_armed is True

    fetcher.set_price("1005001111111111", 88.0)
    back = await checker.check_all()
    assert back[0].alerted


@pytest.mark.asyncio
async def test_setrange_and_missing_fixture(db, checker, fetcher):
    watch = db.add_watch(
        product_id="1005002222222222",
        url="https://www.aliexpress.com/item/1005002222222222.html",
        nickname="Battery",
        min_price=None,
        max_price=90,
        ship_to="US",
        currency="USD",
    )
    high = await checker.check_all(watch.id)
    assert high[0].fetch.price == 129
    assert high[0].alerted is False

    db.set_range(watch.id, 100, 140)
    in_band = await checker.check_all(watch.id)
    assert in_band[0].alerted

    missing = db.add_watch(
        product_id="0000000000000000",
        url="https://www.aliexpress.com/item/0000000000000000.html",
        nickname="Ghost",
        min_price=None,
        max_price=10,
        ship_to="US",
        currency="USD",
    )
    failed = await checker.check_all(missing.id)
    assert failed[0].fetch.ok is False
    report = format_check_report(failed)
    assert "failed" in report
