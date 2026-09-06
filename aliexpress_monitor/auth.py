"""Restrict the bot to a single owner chat."""

from __future__ import annotations

from aliexpress_monitor.config import Settings
from aliexpress_monitor.db import Database

OWNER_KEY = "owner_chat_id"


def owner_chat_id(settings: Settings, db: Database) -> str | None:
    if settings.telegram_chat_id:
        return str(settings.telegram_chat_id)
    stored = db.get_setting(OWNER_KEY)
    return stored


def is_owner(settings: Settings, db: Database, chat_id: int | str) -> bool:
    owner = owner_chat_id(settings, db)
    if owner is None:
        return False
    return str(chat_id) == str(owner)


def claim_or_reject(
    settings: Settings,
    db: Database,
    chat_id: int | str,
) -> tuple[bool, str]:
    """Return (allowed, message_suffix). First /start may claim the bot."""
    chat = str(chat_id)
    configured = settings.telegram_chat_id
    if configured:
        if chat == str(configured):
            db.set_setting(OWNER_KEY, chat)
            return True, (
                f"This chat id is {chat}. It is already saved in TELEGRAM_CHAT_ID."
            )
        return False, (
            "This bot is locked to another chat. "
            "If this is your bot, set TELEGRAM_CHAT_ID to this chat's id: "
            f"{chat}"
        )

    stored = db.get_setting(OWNER_KEY)
    if stored is None:
        db.set_setting(OWNER_KEY, chat)
        return True, (
            f"I'll send alerts to this chat (id {chat}). "
            "Add TELEGRAM_CHAT_ID=" + chat + " to your .env so this survives a reset."
        )
    if stored == chat:
        return True, f"This chat id is {chat}."
    return False, (
        "This bot is already claimed by another chat. "
        f"Your chat id is {chat}."
    )
