"""Telegram command handlers."""

from __future__ import annotations

import logging

from telegram import BotCommand, Update
from telegram.ext import Application, CommandHandler, ContextTypes

from aliexpress_monitor.auth import claim_or_reject, is_owner, owner_chat_id
from aliexpress_monitor.checker import Checker
from aliexpress_monitor.config import Settings
from aliexpress_monitor.db import Database
from aliexpress_monitor.formatting import (
    HELP_TEXT,
    START_TEXT,
    format_alert,
    format_check_report,
    format_history,
    format_watch_list,
    parse_add_args,
    parse_id,
    parse_setrange_args,
)

logger = logging.getLogger(__name__)

COMMANDS = [
    BotCommand("start", "Welcome and claim this chat"),
    BotCommand("help", "Show commands"),
    BotCommand("add", "Add a product URL and max price"),
    BotCommand("list", "List watched items"),
    BotCommand("remove", "Remove a watch by id"),
    BotCommand("setrange", "Set min and max price for a watch"),
    BotCommand("check", "Check prices now"),
    BotCommand("history", "Recent prices for a watch"),
    BotCommand("reset", "Allow the next alert for a watch"),
    BotCommand("whoami", "Show this chat id"),
]


def _deps(context: ContextTypes.DEFAULT_TYPE) -> tuple[Settings, Database, Checker]:
    return (
        context.application.bot_data["settings"],
        context.application.bot_data["db"],
        context.application.bot_data["checker"],
    )


async def _require_owner(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    settings, db, _ = _deps(context)
    chat = update.effective_chat
    if chat is None or update.effective_message is None:
        return False
    if is_owner(settings, db, chat.id):
        return True
    owner = owner_chat_id(settings, db)
    if owner is None:
        await update.effective_message.reply_text(
            "Send /start first so I can bind alerts to this chat."
        )
    else:
        await update.effective_message.reply_text(
            "This bot only talks to its owner chat. "
            f"Your chat id is {chat.id}."
        )
    return False


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings, db, _ = _deps(context)
    chat = update.effective_chat
    if chat is None or update.effective_message is None:
        return
    allowed, note = claim_or_reject(settings, db, chat.id)
    if not allowed:
        await update.effective_message.reply_text(note)
        return
    await update.effective_message.reply_text(START_TEXT + "\n" + note)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_owner(update, context):
        return
    await update.effective_message.reply_text(HELP_TEXT)


async def cmd_whoami(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    if chat is None or update.effective_message is None:
        return
    await update.effective_message.reply_text(
        f"Chat id: {chat.id}\nPut TELEGRAM_CHAT_ID={chat.id} in your .env file."
    )


async def cmd_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_owner(update, context):
        return
    settings, db, _ = _deps(context)
    try:
        parsed = parse_add_args(context.args or [])
    except ValueError as exc:
        await update.effective_message.reply_text(str(exc))
        return
    watch = db.add_watch(
        product_id=parsed.product_id,
        url=parsed.url,
        nickname=parsed.nickname,
        min_price=None,
        max_price=parsed.max_price,
        ship_to=settings.ship_to_country,
        currency=settings.currency,
    )
    await update.effective_message.reply_text(
        f"Watching #{watch.id} {watch.display_name()}\n"
        f"Target: {watch.target_label()}  ·  ship-to {watch.ship_to}/{watch.currency}\n"
        f"{watch.url}\n\n"
        "I'll alert you when the price is at or below your max. "
        "Use /setrange to set a min–max band. /check to fetch now."
    )


async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_owner(update, context):
        return
    _, db, _ = _deps(context)
    await update.effective_message.reply_text(format_watch_list(db.list_watches()))


async def cmd_remove(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_owner(update, context):
        return
    _, db, _ = _deps(context)
    try:
        watch_id = parse_id(context.args or [], "remove")
    except ValueError as exc:
        await update.effective_message.reply_text(str(exc))
        return
    watch = db.get_watch(watch_id)
    if watch is None or not db.remove_watch(watch_id):
        await update.effective_message.reply_text(f"No watch #{watch_id}.")
        return
    await update.effective_message.reply_text(
        f"Removed #{watch.id} {watch.display_name()}."
    )


async def cmd_setrange(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_owner(update, context):
        return
    _, db, _ = _deps(context)
    try:
        watch_id, min_price, max_price = parse_setrange_args(context.args or [])
    except ValueError as exc:
        await update.effective_message.reply_text(str(exc))
        return
    watch = db.set_range(watch_id, min_price, max_price)
    if watch is None:
        await update.effective_message.reply_text(f"No watch #{watch_id}.")
        return
    await update.effective_message.reply_text(
        f"#{watch.id} {watch.display_name()} target is now {watch.target_label()}. "
        "Alert is re-armed."
    )


async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_owner(update, context):
        return
    _, db, _ = _deps(context)
    try:
        watch_id = parse_id(context.args or [], "reset")
    except ValueError as exc:
        await update.effective_message.reply_text(str(exc))
        return
    watch = db.reset_alert(watch_id)
    if watch is None:
        await update.effective_message.reply_text(f"No watch #{watch_id}.")
        return
    await update.effective_message.reply_text(
        f"#{watch.id} will alert again the next time it is in range."
    )


async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_owner(update, context):
        return
    _, db, _ = _deps(context)
    try:
        watch_id = parse_id(context.args or [], "history")
    except ValueError as exc:
        await update.effective_message.reply_text(str(exc))
        return
    watch = db.get_watch(watch_id)
    if watch is None:
        await update.effective_message.reply_text(f"No watch #{watch_id}.")
        return
    await update.effective_message.reply_text(
        format_history(watch, db.history(watch_id, limit=12))
    )


async def cmd_check(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_owner(update, context):
        return
    _, _, checker = _deps(context)
    watch_id = None
    if context.args:
        try:
            watch_id = parse_id(context.args, "check")
        except ValueError as exc:
            await update.effective_message.reply_text(str(exc))
            return
        if checker.db.get_watch(watch_id) is None:
            await update.effective_message.reply_text(f"No watch #{watch_id}.")
            return
    await update.effective_message.reply_text("Checking prices…")
    try:
        outcomes = await checker.check_all(watch_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Forced check failed")
        await update.effective_message.reply_text(f"Check failed: {exc}")
        return
    await update.effective_message.reply_text(format_check_report(outcomes))
    for outcome in outcomes:
        if outcome.alerted:
            await update.effective_message.reply_text(format_alert(outcome))


async def scheduled_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.application.bot_data["settings"]
    db: Database = context.application.bot_data["db"]
    checker: Checker = context.application.bot_data["checker"]
    logger.info("Scheduled price check starting")
    try:
        outcomes = await checker.check_all()
    except Exception:
        logger.exception("Scheduled check crashed")
        return
    chat_id = owner_chat_id(settings, db)
    if not chat_id:
        logger.info("No owner chat yet; skipping Telegram delivery")
        return
    for outcome in outcomes:
        if not outcome.alerted:
            continue
        try:
            await context.bot.send_message(chat_id=int(chat_id), text=format_alert(outcome))
        except Exception:
            logger.exception("Failed to send alert for watch #%s", outcome.watch.id)


async def post_init(application: Application) -> None:
    try:
        await application.bot.set_my_commands(COMMANDS)
    except Exception:
        logger.warning("Could not register bot command menu", exc_info=True)
    settings: Settings = application.bot_data["settings"]
    if application.job_queue is None:
        logger.warning("JobQueue is missing; scheduled checks will not run.")
        return
    application.job_queue.run_repeating(
        scheduled_job,
        interval=settings.check_interval_seconds,
        first=45,
        name="price_check",
    )
    logger.info(
        "Scheduler armed: every %s seconds (first run in 45s)",
        settings.check_interval_seconds,
    )


def build_application(settings: Settings, db: Database, checker: Checker) -> Application:
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is empty.")
    application = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .post_init(post_init)
        .build()
    )
    application.bot_data["settings"] = settings
    application.bot_data["db"] = db
    application.bot_data["checker"] = checker
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("help", cmd_help))
    application.add_handler(CommandHandler("whoami", cmd_whoami))
    application.add_handler(CommandHandler("add", cmd_add))
    application.add_handler(CommandHandler("list", cmd_list))
    application.add_handler(CommandHandler("remove", cmd_remove))
    application.add_handler(CommandHandler("setrange", cmd_setrange))
    application.add_handler(CommandHandler("reset", cmd_reset))
    application.add_handler(CommandHandler("history", cmd_history))
    application.add_handler(CommandHandler("check", cmd_check))
    return application
