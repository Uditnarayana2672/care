from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


def make_engine(url: str | None = None):
    url = url or get_settings().database_url
    kw = {}
    if url.startswith("sqlite"):
        kw["connect_args"] = {"timeout": 30}
    eng = create_async_engine(url, **kw)
    if url.startswith("sqlite"):
        from sqlalchemy import event

        @event.listens_for(eng.sync_engine, "connect")
        def _wal(conn, _rec):  # noqa: ANN001
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=30000")

    return eng


engine = make_engine()
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as s:
        yield s


async def init_models() -> None:
    from app import models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
