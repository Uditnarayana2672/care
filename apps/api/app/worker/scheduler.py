from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config import get_settings
from app.worker import jobs


def build_scheduler() -> AsyncIOScheduler:
    tz = get_settings().tz
    sch = AsyncIOScheduler(timezone=tz)
    sch.add_job(jobs.daily_todo_build, CronTrigger(hour=5, minute=30, timezone=tz), id="daily_todos")
    sch.add_job(jobs.trend_scan, "interval", hours=6, id="trend_scan")
    sch.add_job(jobs.nightly_memory_refresh, CronTrigger(hour=2, minute=0, timezone=tz), id="memory_refresh")
    sch.add_job(jobs.retry_failed_retains, "interval", minutes=5, id="retry_retains")
    sch.add_job(jobs.publish_checkins, "interval", seconds=60, id="checkins")
    return sch
