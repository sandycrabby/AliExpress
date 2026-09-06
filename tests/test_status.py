import json

import pytest

from aliexpress_monitor.status import StatusHandler


@pytest.mark.asyncio
async def test_status_page_lists_watches(db, checker, settings):
    db.add_watch(
        product_id="1005001111111111",
        url="https://www.aliexpress.com/item/1005001111111111.html",
        nickname="Solar panel",
        min_price=None,
        max_price=95,
        ship_to="US",
        currency="USD",
    )
    handler = StatusHandler(settings, db, checker)

    class FakeWriter:
        def __init__(self):
            self.buf = bytearray()
            self.closed = False

        def write(self, data: bytes) -> None:
            self.buf.extend(data)

        async def drain(self) -> None:
            return None

        def close(self) -> None:
            self.closed = True

        async def wait_closed(self) -> None:
            return None

    class FakeReader:
        def __init__(self, raw: bytes):
            self.raw = raw

        async def read(self, _n: int) -> bytes:
            return self.raw

    writer = FakeWriter()
    await handler.handle(FakeReader(b"GET / HTTP/1.1\r\nHost: x\r\n\r\n"), writer)
    body = bytes(writer.buf).split(b"\r\n\r\n", 1)[1].decode("utf-8")
    assert "Solar panel" in body
    assert "AliExpress price monitor" in body

    writer = FakeWriter()
    await handler.handle(FakeReader(b"GET /health HTTP/1.1\r\n\r\n"), writer)
    payload = json.loads(bytes(writer.buf).split(b"\r\n\r\n", 1)[1])
    assert payload["ok"] is True
    assert payload["watch_count"] == 1

