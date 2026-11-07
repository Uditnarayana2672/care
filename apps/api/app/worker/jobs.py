import logging
from datetime import timedelta

from sqlalchemy import select

from app.agent.actions import checkin_prompt
from app.agent.runner import load_ctx
from app.core import events
from app.core.db import SessionLocal
from app.core.time import at_local, now, today
from app.memory.service import get_memory
from app.models import Assignment, Patient, Todo, User
from app.orchestrator.generate import generate_for_all
from app.orchestrator.hints import refresh_hints
from app.trends.watch import scan_patient

log = logging.getLogger(__name__)


async def daily_todo_build() -> None:
    async with SessionLocal() as s:
        n = await generate_for_all(s, today())
    log.info("daily todo build: %s todos", n)


async def trend_scan() -> None:
    mem = get_memory()
    async with SessionLocal() as s:
        for p in await s.scalars(select(Patient).where(Patient.status == "active")):
            await scan_patient(s, mem, p)


async def nightly_memory_refresh() -> None:
    mem = get_memory()
    async with SessionLocal() as s:
        for p in await s.scalars(select(Patient).where(Patient.status == "active")):
            await mem.refresh_mental_models(p)
            await refresh_hints(mem, p)


async def retry_failed_retains() -> None:
    async with SessionLocal() as s:
        n = await get_memory().retry_failed(s)
    if n:
        log.info("retried %s failed retains", n)


async def publish_checkins() -> None:
    """W3: todos due + 30 min and not done → agent check-in message to assigned caretakers (Redis pub/sub)."""
    mem = get_memory()
    async with SessionLocal() as s:
        cutoff = now() - timedelta(minutes=30)
        todos = list(await s.scalars(select(Todo).where(Todo.due_date == today(), Todo.status.in_(["todo", "in_progress"]),
                                                        Todo.checkin_sent.is_(False))))
        for t in todos:
            if at_local(t.due_date, t.due_time) > cutoff:
                continue
            uids = list(await s.scalars(select(Assignment.user_id).where(Assignment.patient_id == t.patient_id, Assignment.active.is_(True))))
            for uid in uids:
                u = await s.get(User, uid)
                if not u:
                    continue
                ctx = await load_ctx(s, u, mem, None)
                await events.publish(f"user:{uid}", {"type": "checkin", "todo_id": str(t.id), "prompt": checkin_prompt(ctx, t)})
            t.checkin_sent = True
        await s.commit()
