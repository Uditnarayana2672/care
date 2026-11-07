"""Todo state changes. One function used by REST (Kanban drag), chat tools, and tests."""
import uuid
from dataclasses import dataclass, field

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import events
from app.core.time import now
from app.memory.patterns import todo_pattern
from app.memory.service import MemoryService
from app.models import Patient, Suggestion, Todo, TodoEvent, User
from app.services.facts import todo_outcome_fact

STATUSES = {"todo", "in_progress", "done", "not_done", "skipped"}
ALLOWED = {
    "todo": {"in_progress", "done", "not_done", "skipped"},
    "in_progress": {"done", "not_done", "skipped", "todo"},
    "not_done": {"todo", "done", "in_progress"},
    "skipped": {"todo", "done"},
    "done": {"todo"},
}
REASONS = ["Refused", "Asleep", "Unwell", "No time", "Other"]


@dataclass
class StatusResult:
    todo: Todo
    suggestion: Suggestion | None = None
    coordinator_hint: str | None = None
    notes: list[str] = field(default_factory=list)


async def set_status(
    session: AsyncSession, memory: MemoryService, user: User, todo: Todo, to_status: str,
    reason: str = "", *, at=None,
) -> StatusResult:
    if to_status not in STATUSES:
        raise HTTPException(422, f"Unknown status {to_status}")
    if to_status in ("not_done", "skipped") and not reason.strip():
        raise HTTPException(422, "A reason is required for not done / skipped")
    frm = todo.status
    if frm == to_status:
        return StatusResult(todo)
    if to_status not in ALLOWED.get(frm, set()):
        raise HTTPException(409, f"Cannot move from {frm} to {to_status}")
    at = at or now()
    patient = await session.get(Patient, todo.patient_id)
    assert patient
    todo.status = to_status
    todo.status_note = reason
    todo.caretaker_id = user.id
    ev = TodoEvent(todo_id=todo.id, actor_id=user.id, from_status=frm, to_status=to_status, reason=reason, at=at)
    session.add(ev)
    await session.flush()
    meta = {"todo_id": todo.id, "category": todo.category, "status": to_status, "caretaker_id": user.id,
            "caretaker_name": user.full_name.split()[0], "template_id": todo.template_id or "",
            "brief": f"{todo.title}: {to_status.replace('_', ' ')}" + (f" — {reason}" if reason else "")}
    pat = todo_pattern(todo.title, to_status, reason)
    if pat:
        meta.update(pattern=pat[0], pattern_text=pat[1], pattern_kind=pat[2])
        from app.orchestrator.hints import invalidate

        await invalidate(patient)
    await memory.retain_fact(
        patient, text=todo_outcome_fact(patient, todo, user, to_status, reason, at), occurred_at=at,
        context="todo_outcome", source_type="todo_event", source_id=ev.id, metadata=meta, session=session,
    )
    await session.commit()
    result = StatusResult(todo)
    if to_status in ("not_done", "skipped"):
        from app.learning.failures import evaluate_failures

        out = await evaluate_failures(session, memory, patient, todo)
        result.suggestion, result.coordinator_hint = out.suggestion, out.coordinator_hint
    await events.publish(f"user:{user.id}", {"type": "board_changed", "todo_id": str(todo.id)})
    return result


async def get_todo_for(session: AsyncSession, todo_id: uuid.UUID) -> Todo:
    todo = await session.get(Todo, todo_id)
    if not todo:
        raise HTTPException(404, "Todo not found")
    return todo
