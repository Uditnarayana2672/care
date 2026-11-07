from datetime import UTC, date, datetime, time

from app.core.config import get_settings


def now() -> datetime:
    return datetime.now(UTC)


def local_now() -> datetime:
    return now().astimezone(get_settings().tz)


def today() -> date:
    return local_now().date()


def at_local(d: date, t: time) -> datetime:
    return datetime.combine(d, t, tzinfo=get_settings().tz).astimezone(UTC)


def aware(dt: datetime) -> datetime:
    """SQLite drops tzinfo; treat naive values as UTC."""
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def fmt_dt(dt: datetime) -> str:
    l = aware(dt).astimezone(get_settings().tz)
    return f"{l.day} {l.strftime('%b %Y')} {l.strftime('%H:%M')}"


def fmt_day(dt: datetime) -> str:
    l = aware(dt).astimezone(get_settings().tz)
    return f"{l.day} {l.strftime('%b')}"
