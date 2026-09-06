"""Tiny HTTP status page so you can see watches without opening Telegram."""

from __future__ import annotations

import asyncio
import html
import json
import logging
from datetime import datetime, timezone
from http import HTTPStatus

from aliexpress_monitor.checker import Checker
from aliexpress_monitor.config import Settings
from aliexpress_monitor.db import Database
from aliexpress_monitor.formatting import money

logger = logging.getLogger(__name__)


def _payload(settings: Settings, db: Database, checker: Checker) -> dict:
    watches = []
    for watch in db.list_watches():
        watches.append(
            {
                "id": watch.id,
                "name": watch.display_name(),
                "product_id": watch.product_id,
                "url": watch.url,
                "target": watch.target_label(),
                "last_price": watch.last_price,
                "currency": watch.currency,
                "ship_to": watch.ship_to,
                "last_checked_at": watch.last_checked_at,
                "last_error": watch.last_error,
                "alert_armed": watch.alert_armed,
            }
        )
    return {
        "ok": True,
        "service": "aliexpress-monitor",
        "fetch_mode": settings.fetch_mode,
        "ship_to": settings.ship_to_country,
        "currency": settings.currency,
        "check_interval_seconds": settings.check_interval_seconds,
        "last_run_at": checker.last_run_at,
        "last_run_summary": checker.last_run_summary,
        "watch_count": len(watches),
        "watches": watches,
        "server_time": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }


def _html_page(data: dict) -> str:
    rows = []
    for watch in data["watches"]:
        price = money(watch["last_price"], watch["currency"])
        err = html.escape(watch["last_error"] or "")
        rows.append(
            "<tr>"
            f"<td>#{watch['id']}</td>"
            f"<td>{html.escape(watch['name'])}</td>"
            f"<td>{html.escape(price)}</td>"
            f"<td>{html.escape(watch['target'])}</td>"
            f"<td>{html.escape(watch['ship_to'])}/{html.escape(watch['currency'])}</td>"
            f"<td>{html.escape(watch['last_checked_at'] or 'never')}</td>"
            f"<td>{err}</td>"
            f"<td><a href=\"{html.escape(watch['url'])}\">link</a></td>"
            "</tr>"
        )
    table = (
        "<tr><td colspan='8'>No watches yet. Use the Telegram bot /add command.</td></tr>"
        if not rows
        else "".join(rows)
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>AliExpress price monitor</title>
  <style>
    body {{ font-family: Georgia, serif; margin: 2rem; color: #222; background: #faf8f5; }}
    h1 {{ font-size: 1.4rem; }}
    .meta {{ color: #555; margin-bottom: 1.5rem; }}
    table {{ border-collapse: collapse; width: 100%; background: #fff; }}
    th, td {{ border: 1px solid #ddd; padding: 0.5rem 0.6rem; text-align: left; font-size: 0.95rem; }}
    th {{ background: #efeae2; }}
    a {{ color: #0b5; }}
    code {{ background: #efeae2; padding: 0.1rem 0.3rem; }}
  </style>
</head>
<body>
  <h1>AliExpress price monitor</h1>
  <p class="meta">
    Mode <code>{html.escape(data['fetch_mode'])}</code>
    · ship-to {html.escape(data['ship_to'])}/{html.escape(data['currency'])}
    · interval {data['check_interval_seconds']}s
    · last run {html.escape(data['last_run_at'] or 'not yet')}
    ({html.escape(data['last_run_summary'] or '—')})
  </p>
  <table>
    <thead>
      <tr>
        <th>Id</th><th>Item</th><th>Last price</th><th>Target</th>
        <th>Locale</th><th>Checked</th><th>Error</th><th>Link</th>
      </tr>
    </thead>
    <tbody>{table}</tbody>
  </table>
</body>
</html>
"""


class StatusHandler:
    def __init__(self, settings: Settings, db: Database, checker: Checker) -> None:
        self.settings = settings
        self.db = db
        self.checker = checker

    async def handle(self, reader, writer) -> None:
        try:
            raw = await reader.read(4096)
            request_line = raw.decode("latin1", errors="replace").split("\r\n", 1)[0]
            parts = request_line.split(" ")
            path = parts[1] if len(parts) >= 2 else "/"
            path = path.split("?", 1)[0]
            data = _payload(self.settings, self.db, self.checker)
            if path in {"/health", "/healthz"}:
                body = json.dumps(
                    {
                        "ok": True,
                        "watch_count": data["watch_count"],
                        "last_run_at": data["last_run_at"],
                    }
                ).encode("utf-8")
                content_type = "application/json; charset=utf-8"
            elif path in {"/", "/status"}:
                body = _html_page(data).encode("utf-8")
                content_type = "text/html; charset=utf-8"
            elif path == "/status.json":
                body = json.dumps(data, indent=2).encode("utf-8")
                content_type = "application/json; charset=utf-8"
            else:
                body = b"Not found"
                await self._write(writer, HTTPStatus.NOT_FOUND, "text/plain", body)
                return
            await self._write(writer, HTTPStatus.OK, content_type, body)
        except Exception:
            logger.exception("Status handler failed")
            try:
                await self._write(
                    writer, HTTPStatus.INTERNAL_SERVER_ERROR, "text/plain", b"error"
                )
            except Exception:
                pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    async def _write(self, writer, status: HTTPStatus, content_type: str, body: bytes) -> None:
        header = (
            f"HTTP/1.1 {int(status)} {status.phrase}\r\n"
            f"Content-Type: {content_type}\r\n"
            f"Content-Length: {len(body)}\r\n"
            "Connection: close\r\n"
            "\r\n"
        )
        writer.write(header.encode("latin1") + body)
        await writer.drain()


async def start_status_server(settings: Settings, db: Database, checker: Checker):
    if not settings.status_port:
        logger.info("Status page disabled (STATUS_PORT=0)")
        return None
    handler = StatusHandler(settings, db, checker)
    server = await asyncio.start_server(
        handler.handle, settings.status_host, settings.status_port
    )
    logger.info(
        "Status page listening on http://%s:%s/",
        settings.status_host,
        settings.status_port,
    )
    return server
