from aliexpress_monitor.db import Database


def test_watch_crud_and_history(db: Database):
    watch = db.add_watch(
        product_id="1005001111111111",
        url="https://www.aliexpress.com/item/1005001111111111.html",
        nickname="Solar",
        min_price=None,
        max_price=95,
        ship_to="US",
        currency="USD",
    )
    assert watch.id == 1
    assert db.list_watches()[0].nickname == "Solar"

    db.record_success(
        watch,
        price=89.5,
        currency="USD",
        title="200W Solar Panel Kit",
        source="mock",
        alerted=True,
        rearm=False,
    )
    updated = db.get_watch(watch.id)
    assert updated.last_price == 89.5
    assert updated.alert_armed is False
    assert updated.last_alert_price == 89.5
    assert len(db.history(watch.id)) == 1

    ranged = db.set_range(watch.id, 70, 90)
    assert ranged.min_price == 70
    assert ranged.max_price == 90
    assert ranged.alert_armed is True

    db.reset_alert(watch.id)
    assert db.get_watch(watch.id).alert_armed is True

    db.record_failure(watch.id, "timeout")
    assert db.get_watch(watch.id).last_error == "timeout"

    assert db.remove_watch(watch.id)
    assert db.list_watches() == []


def test_settings_roundtrip(db: Database):
    assert db.get_setting("owner_chat_id") is None
    db.set_setting("owner_chat_id", "12345")
    assert db.get_setting("owner_chat_id") == "12345"
