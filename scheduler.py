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
        
        # تخطي عطل نهاية الأسبوع والأعياد
        if now_ny.weekday() >= 5 or _is_market_holiday(now_ny):
            logger.info("Skipping report — market closed.")
            return
            
        # منع التكرار في نفس اليوم
        if self._last_sent_date == now_utc.date():
            return
        self._last_sent_date = now_utc.date()
        
        await self.send_callback()

    def start(self) -> None:
        # إرسال التقرير الساعة 12:20 بتوقيت مكة (وهو ما يعادل 21:20 بتوقيت UTC)
        self.scheduler.add_job(
            self._job, 
            CronTrigger(hour=21, minute=20, timezone="UTC"), 
            id="postmarket_report"
        )
        self.scheduler.start()
        logger.info("Scheduler started. Next report at 21:20 UTC (12:20 AM Mecca Time).")
