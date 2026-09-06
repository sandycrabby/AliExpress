"""Process entry: Telegram bot + scheduler + status page, or a one-shot CLI."""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys

from aliexpress_monitor.checker import Checker
from aliexpress_monitor.config import Settings, load_settings
from aliexpress_monitor.db import Database
from aliexpress_monitor.fetchers import build_fetcher
from aliexpress_monitor.formatting import (
    format_check_report,
    format_history,
    format_watch_list,
    parse_add_args,
    parse_setrange_args,
)
from aliexpress_monitor.status import start_status_server

logger = logging.getLogger(__name__)


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.INFO)


def build_runtime(settings: Settings | None = None) -> tuple[Settings, Database, Checker]:
    settings = settings or load_settings()
    db = Database(settings.database_path)
    db.init()
    fetcher = build_fetcher(settings)
    checker = Checker(db, fetcher, settings)
    return settings, db, checker


def _print(text: str) -> None:
    sys.stdout.write(text + "\n")


def cmd_add(settings: Settings, db: Database, raw_args: list[str]) -> int:
    parsed = parse_add_args(raw_args)
    watch = db.add_watch(
        product_id=parsed.product_id,
        url=parsed.url,
        nickname=parsed.nickname,
        min_price=None,
        max_price=parsed.max_price,
        ship_to=settings.ship_to_country,
        currency=settings.currency,
    )
    _print(f"Added #{watch.id} {watch.display_name()} target {watch.target_label()}")
    return 0


def cmd_list(db: Database) -> int:
    _print(format_watch_list(db.list_watches()))
    return 0


def cmd_remove(db: Database, raw_args: list[str]) -> int:
    if not raw_args or not raw_args[0].isdigit():
        raise ValueError("Usage: python -m aliexpress_monitor remove <id>")
    watch_id = int(raw_args[0])
    watch = db.get_watch(watch_id)
    if watch is None or not db.remove_watch(watch_id):
        _print(f"No watch #{watch_id}.")
        return 1
    _print(f"Removed #{watch.id} {watch.display_name()}.")
    return 0


def cmd_setrange(db: Database, raw_args: list[str]) -> int:
    watch_id, min_price, max_price = parse_setrange_args(raw_args)
    watch = db.set_range(watch_id, min_price, max_price)
    if watch is None:
        _print(f"No watch #{watch_id}.")
        return 1
    _print(f"#{watch.id} target is now {watch.target_label()}.")
    return 0


def cmd_history(db: Database, raw_args: list[str]) -> int:
    if not raw_args or not raw_args[0].isdigit():
        raise ValueError("Usage: python -m aliexpress_monitor history <id>")
    watch_id = int(raw_args[0])
    watch = db.get_watch(watch_id)
    if watch is None:
        _print(f"No watch #{watch_id}.")
        return 1
    _print(format_history(watch, db.history(watch_id)))
    return 0


async def cmd_check(checker: Checker, raw_args: list[str]) -> int:
    watch_id = int(raw_args[0]) if raw_args and raw_args[0].isdigit() else None
    outcomes = await checker.check_all(watch_id)
    _print(format_check_report(outcomes))
    return 0 if all(o.fetch.ok for o in outcomes) or not outcomes else 2


def _stop_event() -> asyncio.Event:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()

    def _signal(*_args) -> None:
        stop.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal)
        except NotImplementedError:  # pragma: no cover — Windows
            signal.signal(sig, lambda *_: stop.set())
    return stop


async def run_service(settings: Settings, db: Database, checker: Checker) -> None:
    server = await start_status_server(settings, db, checker)
    stop = _stop_event()
    try:
        if not settings.telegram_bot_token:
            logger.warning(
                "TELEGRAM_BOT_TOKEN is empty. Running scheduler + status page only. "
                "Telegram commands will not work until you add a token."
            )
            await _headless_loop(settings, checker, stop)
            return

        from aliexpress_monitor.bot import build_application

        application = build_application(settings, db, checker)
        async with application:
            await application.start()
            if application.updater is None:
                raise RuntimeError("Telegram updater was not created.")
            await application.updater.start_polling(drop_pending_updates=True)
            logger.info("Telegram bot is polling. Status page and scheduler are running.")
            await stop.wait()
            await application.updater.stop()
            await application.stop()
    finally:
        await checker.fetcher.close()
        if server is not None:
            server.close()
            await server.wait_closed()
        db.close()


async def _headless_loop(
    settings: Settings,
    checker: Checker,
    stop: asyncio.Event,
) -> None:
    logger.info(
        "Headless scheduler every %ss (first check in 15s)",
        settings.check_interval_seconds,
    )

    async def _sleep_or_stop(seconds: float) -> bool:
        try:
            await asyncio.wait_for(stop.wait(), timeout=seconds)
            return True
        except asyncio.TimeoutError:
            return False

    if await _sleep_or_stop(15):
        return
    while not stop.is_set():
        try:
            await checker.check_all()
        except Exception:
            logger.exception("Scheduled check crashed")
        if await _sleep_or_stop(settings.check_interval_seconds):
            return


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="AliExpress price monitor (Telegram bot + scheduler).",
    )
    parser.add_argument(
        "command",
        nargs="?",
        default="run",
        choices=["run", "add", "list", "remove", "setrange", "history", "check"],
        help="run (default) starts the bot. Other commands are a local CLI.",
    )
    parser.add_argument("args", nargs=argparse.REMAINDER, help="Command arguments")
    return parser


def main(argv: list[str] | None = None) -> None:
    configure_logging()
    parser = build_parser()
    ns = parser.parse_args(argv)
    try:
        settings, db, checker = build_runtime()
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to start: %s", exc)
        raise SystemExit(2) from exc

    try:
        if ns.command == "run":
            asyncio.run(run_service(settings, db, checker))
            return
        if ns.command == "add":
            raise SystemExit(cmd_add(settings, db, ns.args))
        if ns.command == "list":
            raise SystemExit(cmd_list(db))
        if ns.command == "remove":
            raise SystemExit(cmd_remove(db, ns.args))
        if ns.command == "setrange":
            raise SystemExit(cmd_setrange(db, ns.args))
        if ns.command == "history":
            raise SystemExit(cmd_history(db, ns.args))
        if ns.command == "check":
            raise SystemExit(asyncio.run(cmd_check(checker, ns.args)))
    except ValueError as exc:
        _print(str(exc))
        raise SystemExit(1) from exc
    finally:
        if ns.command != "run":
            try:
                asyncio.run(checker.fetcher.close())
            except RuntimeError:
                pass
            db.close()
