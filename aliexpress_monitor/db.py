"""SQLite storage for watches, price history, and owner chat id."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Any, Iterable

from aliexpress_monitor.models import PricePoint, Watch, utc_now_iso

SCHEMA = """
CREATE TABLE IF NOT EXISTS watches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id TEXT NOT NULL,
    url TEXT NOT NULL,
    nickname TEXT,
    min_price REAL,
    max_price REAL,
    ship_to TEXT NOT NULL DEFAULT 'US',
    currency TEXT NOT NULL DEFAULT 'USD',
    title TEXT,
    last_price REAL,
    last_checked_at TEXT,
    last_error TEXT,
    last_alert_price REAL,
    last_alert_at TEXT,
    alert_armed INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS price_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    watch_id INTEGER NOT NULL,
    price REAL NOT NULL,
    currency TEXT NOT NULL,
    title TEXT,
    fetched_at TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'unknown',
    FOREIGN KEY (watch_id) REFERENCES watches(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_history_watch_time
    ON price_history(watch_id, fetched_at DESC);
"""


def _row_to_watch(row: sqlite3.Row) -> Watch:
    return Watch(
        id=row["id"],
        product_id=row["product_id"],
        url=row["url"],
        nickname=row["nickname"],
        min_price=row["min_price"],
        max_price=row["max_price"],
        ship_to=row["ship_to"],
        currency=row["currency"],
        title=row["title"],
        last_price=row["last_price"],
        last_checked_at=row["last_checked_at"],
        last_error=row["last_error"],
        last_alert_price=row["last_alert_price"],
        last_alert_at=row["last_alert_at"],
        alert_armed=bool(row["alert_armed"]),
        created_at=row["created_at"],
    )


def _row_to_point(row: sqlite3.Row) -> PricePoint:
    return PricePoint(
        id=row["id"],
        watch_id=row["watch_id"],
        price=row["price"],
        currency=row["currency"],
        title=row["title"],
        fetched_at=row["fetched_at"],
        source=row["source"],
    )


class Database:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None

    def connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA journal_mode = WAL")
            self._conn = conn
        return self._conn

    def init(self) -> None:
        with self._lock:
            conn = self.connect()
            conn.executescript(SCHEMA)
            conn.commit()

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    def _execute(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        conn = self.connect()
        return conn.execute(sql, tuple(params))

    def get_setting(self, key: str) -> str | None:
        with self._lock:
            row = self._execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ).fetchone()
            return None if row is None else row["value"]

    def set_setting(self, key: str, value: str) -> None:
        with self._lock:
            self._execute(
                "INSERT INTO settings(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
            self.connect().commit()

    def add_watch(
        self,
        *,
        product_id: str,
        url: str,
        nickname: str | None,
        min_price: float | None,
        max_price: float | None,
        ship_to: str,
        currency: str,
    ) -> Watch:
        with self._lock:
            now = utc_now_iso()
            cur = self._execute(
                """
                INSERT INTO watches (
                    product_id, url, nickname, min_price, max_price,
                    ship_to, currency, alert_armed, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)
                """,
                (
                    product_id,
                    url,
                    nickname,
                    min_price,
                    max_price,
                    ship_to,
                    currency,
                    now,
                ),
            )
            self.connect().commit()
            return self._get_watch_unlocked(cur.lastrowid)

    def get_watch(self, watch_id: int) -> Watch | None:
        with self._lock:
            return self._get_watch_unlocked(watch_id)

    def _get_watch_unlocked(self, watch_id: int) -> Watch | None:
        row = self._execute(
            "SELECT * FROM watches WHERE id = ?", (watch_id,)
        ).fetchone()
        return None if row is None else _row_to_watch(row)

    def list_watches(self) -> list[Watch]:
        with self._lock:
            rows = self._execute("SELECT * FROM watches ORDER BY id").fetchall()
            return [_row_to_watch(r) for r in rows]

    def remove_watch(self, watch_id: int) -> bool:
        with self._lock:
            cur = self._execute("DELETE FROM watches WHERE id = ?", (watch_id,))
            self.connect().commit()
            return cur.rowcount > 0

    def set_range(
        self,
        watch_id: int,
        min_price: float | None,
        max_price: float | None,
    ) -> Watch | None:
        with self._lock:
            self._execute(
                """
                UPDATE watches
                SET min_price = ?, max_price = ?, alert_armed = 1
                WHERE id = ?
                """,
                (min_price, max_price, watch_id),
            )
            self.connect().commit()
            return self._get_watch_unlocked(watch_id)

    def reset_alert(self, watch_id: int) -> Watch | None:
        with self._lock:
            self._execute(
                "UPDATE watches SET alert_armed = 1 WHERE id = ?",
                (watch_id,),
            )
            self.connect().commit()
            return self._get_watch_unlocked(watch_id)

    def record_success(
        self,
        watch: Watch,
        *,
        price: float,
        currency: str,
        title: str | None,
        source: str,
        alerted: bool,
        rearm: bool,
    ) -> None:
        with self._lock:
            now = utc_now_iso()
            self._execute(
                """
                INSERT INTO price_history (
                    watch_id, price, currency, title, fetched_at, source
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (watch.id, price, currency, title, now, source),
            )
            armed = 1 if rearm else (0 if alerted else int(watch.alert_armed))
            last_alert_price = price if alerted else watch.last_alert_price
            last_alert_at = now if alerted else watch.last_alert_at
            self._execute(
                """
                UPDATE watches
                SET last_price = ?, last_checked_at = ?, last_error = NULL,
                    title = COALESCE(?, title), currency = ?,
                    last_alert_price = ?, last_alert_at = ?,
                    alert_armed = ?
                WHERE id = ?
                """,
                (
                    price,
                    now,
                    title,
                    currency,
                    last_alert_price,
                    last_alert_at,
                    armed,
                    watch.id,
                ),
            )
            self.connect().commit()

    def record_failure(self, watch_id: int, error: str) -> None:
        with self._lock:
            now = utc_now_iso()
            self._execute(
                """
                UPDATE watches
                SET last_checked_at = ?, last_error = ?
                WHERE id = ?
                """,
                (now, error, watch_id),
            )
            self.connect().commit()

    def history(self, watch_id: int, limit: int = 10) -> list[PricePoint]:
        with self._lock:
            rows = self._execute(
                """
                SELECT * FROM price_history
                WHERE watch_id = ?
                ORDER BY fetched_at DESC, id DESC
                LIMIT ?
                """,
                (watch_id, limit),
            ).fetchall()
            return [_row_to_point(r) for r in rows]

    def set_meta(self, key: str, value: str) -> None:
        self.set_setting(key, value)

    def get_meta(self, key: str) -> str | None:
        return self.get_setting(key)
