import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)
NY_TZ = ZoneInfo("America/New_York")

def _is_market_holiday(dt: datetime) -> bool:
    holidays = {
        (2025, 1, 1), (2025, 1, 20), (2025, 2, 17), (2025, 4, 18),
        (2025, 5, 26), (2025, 6, 19), (2025, 7, 4), (2025, 9, 1),
        (2025, 11, 27), (2025, 12, 25),
        (2026, 1, 1), (2026, 1, 19), (2026, 2, 16), (2026, 4, 3),
        (2026, 5, 25), (2026, 6, 19), (2026, 7, 3), (2026, 9, 7),
        (2026, 11, 26), (2026, 12, 25),
    }
    return (dt.year, dt.month, dt.day) in holidays

class ReportScheduler:
    def __init__(self, send_callback):
        self.scheduler = AsyncIOScheduler(timezone="UTC")
        self.send_callback = send_callback
        self._last_sent_date = None

    async def _job(self) -> None:
        now_utc = datetime.utcnow()
        now_ny = now_utc.astimezone(NY_TZ)
        if now_ny.weekday() >= 5 or _is_market_holiday(now_ny):
            logger.info("Skipping report — market closed.")
            return
        if self._last_sent_date == now_utc.date():
            return
        self._last_sent_date = now_utc.date()
        await self.send_callback()

    def start(self) -> None:
        self.scheduler.add_job(self._job, CronTrigger(hour=13, minute=0, timezone="UTC"), id="premarket")
        self.scheduler.add_job(self._job, CronTrigger(hour=20, minute=15, timezone="UTC"), id="postmarket")
        self.scheduler.start()
        logger.info("Scheduler started.")
