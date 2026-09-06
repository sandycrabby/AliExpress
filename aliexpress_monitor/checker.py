"""Run a price-check cycle: fetch, persist history, decide alerts."""

from __future__ import annotations

import asyncio
import logging

from aliexpress_monitor.alerts import decide_alert
from aliexpress_monitor.config import Settings
from aliexpress_monitor.db import Database
from aliexpress_monitor.fetchers import PriceFetcher
from aliexpress_monitor.models import CheckOutcome, FetchResult, Watch, utc_now_iso

logger = logging.getLogger(__name__)


class Checker:
    def __init__(
        self,
        db: Database,
        fetcher: PriceFetcher,
        settings: Settings,
    ) -> None:
        self.db = db
        self.fetcher = fetcher
        self.settings = settings
        self.last_run_at: str | None = None
        self.last_run_summary: str | None = None
        self._lock = asyncio.Lock()

    async def check_watch(self, watch: Watch) -> CheckOutcome:
        logger.info("Checking watch #%s (%s)", watch.id, watch.display_name())
        fetch = await self.fetcher.fetch(
            product_id=watch.product_id,
            url=watch.url,
            ship_to=watch.ship_to,
            currency=watch.currency,
        )
        previous = watch.last_price

        if not fetch.ok or fetch.price is None:
            error = fetch.error or "Unknown fetch error"
            self.db.record_failure(watch.id, error)
            logger.warning("Watch #%s failed: %s", watch.id, error)
            return CheckOutcome(
                watch=watch,
                fetch=fetch,
                previous_price=previous,
                alerted=False,
                alert_reason=None,
                rearmed=False,
            )

        decision = decide_alert(
            watch,
            fetch.price,
            drop_percent=self.settings.alert_drop_percent,
            drop_abs=self.settings.alert_drop_abs,
        )
        self.db.record_success(
            watch,
            price=fetch.price,
            currency=fetch.currency or watch.currency,
            title=fetch.title,
            source=fetch.source,
            alerted=decision.should_alert,
            rearm=decision.rearm,
        )
        logger.info(
            "Watch #%s price=%s %s (was %s) in_range=%s alert=%s",
            watch.id,
            fetch.price,
            fetch.currency or watch.currency,
            previous,
            decision.in_range,
            decision.reason,
        )
        return CheckOutcome(
            watch=watch,
            fetch=fetch,
            previous_price=previous,
            alerted=decision.should_alert,
            alert_reason=decision.reason,
            rearmed=decision.rearm,
        )

    async def check_all(
        self,
        watch_id: int | None = None,
    ) -> list[CheckOutcome]:
        async with self._lock:
            if watch_id is not None:
                watch = self.db.get_watch(watch_id)
                watches = [watch] if watch else []
            else:
                watches = self.db.list_watches()

            outcomes: list[CheckOutcome] = []
            for index, watch in enumerate(watches):
                if index and self.settings.check_delay_seconds > 0:
                    await asyncio.sleep(self.settings.check_delay_seconds)
                try:
                    outcomes.append(await self.check_watch(watch))
                except Exception as exc:  # noqa: BLE001
                    logger.exception("Unexpected error checking watch #%s", watch.id)
                    self.db.record_failure(watch.id, str(exc))
                    outcomes.append(
                        CheckOutcome(
                            watch=watch,
                            fetch=FetchResult.failure(str(exc)),
                            previous_price=watch.last_price,
                            alerted=False,
                            alert_reason=None,
                            rearmed=False,
                        )
                    )
            self.last_run_at = utc_now_iso()
            ok = sum(1 for o in outcomes if o.fetch.ok)
            alerts = sum(1 for o in outcomes if o.alerted)
            self.last_run_summary = (
                f"{ok}/{len(outcomes)} ok, {alerts} alert(s)"
                if outcomes
                else "no watches"
            )
            return outcomes
