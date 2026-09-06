from pathlib import Path

from aliexpress_monitor.app import cmd_add, cmd_history, cmd_list, cmd_remove, cmd_setrange
from aliexpress_monitor.checker import Checker
from aliexpress_monitor.db import Database
from aliexpress_monitor.fetchers import MockFetcher
from tests.conftest import make_settings


def test_cli_watch_lifecycle(tmp_path: Path, capsys):
    settings = make_settings(database_path=tmp_path / "cli.db")
    db = Database(settings.database_path)
    db.init()
    try:
        assert (
            cmd_add(
                settings,
                db,
                [
                    "https://www.aliexpress.com/item/1005001111111111.html",
                    "95",
                    "Solar",
                ],
            )
            == 0
        )
        assert cmd_list(db) == 0
        assert cmd_setrange(db, ["1", "70", "95"]) == 0
        assert cmd_history(db, ["1"]) == 0
        assert cmd_remove(db, ["1"]) == 0
        out = capsys.readouterr().out
        assert "Added #1" in out
        assert "Solar" in out
        assert "70–95" in out
        assert "Removed #1" in out
    finally:
        db.close()


async def test_cli_check(tmp_path: Path, capsys):
    settings = make_settings(database_path=tmp_path / "cli.db")
    db = Database(settings.database_path)
    db.init()
    fetcher = MockFetcher(
        prices={"1005001111111111": {"price": 80, "title": "Solar", "currency": "USD"}}
    )
    checker = Checker(db, fetcher, settings)
    cmd_add(
        settings,
        db,
        ["https://www.aliexpress.com/item/1005001111111111.html", "95", "Solar"],
    )
    from aliexpress_monitor.app import cmd_check

    code = await cmd_check(checker, [])
    assert code == 0
    out = capsys.readouterr().out
    assert "ALERT" in out
    assert "$80.00" in out
    db.close()
