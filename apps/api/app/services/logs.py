"""Care log writes (W4): PostgreSQL first, then retain."""
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import events
from app.core.time import now, today
from app.memory.patterns import derive_pattern
from app.memory.service import MemoryService
from app.models import Alert, Allergy, CareLog, Medication, Patient, Suggestion, Todo, User
from app.services import todos as todo_svc
from app.services.facts import log_fact

CATEGORIES = {"medication", "sleep", "diet", "mood", "mobility", "progress", "allergy", "observation"}
URGENT = re.compile(r"\b(fall|fell|fallen|chest pain|can'?t breathe|breathing difficulty|short of breath|unresponsive|bleeding|unconscious)\b", re.I)


@dataclass
class SaveResult:
    log: CareLog
    suggestion: Suggestion | None = None
    new_alerts: list[Alert] = field(default_factory=list)
    todo_marked: Todo | None = None
    urgent: bool = False


async def save_log(
    session: AsyncSession, memory: MemoryService, user: User, patient: Patient, *, category: str,
    structured: dict, narrative: str, severity: str = "normal", observed_at: datetime | None = None,
    chat_message_id=None,
) -> SaveResult:
    observed_at = observed_at or now()
    if URGENT.search(narrative or ""):
        severity = "urgent"
    log = CareLog(patient_id=patient.id, caretaker_id=user.id, category=category, structured=structured,
                  narrative=narrative, severity=severity, observed_at=observed_at, chat_message_id=chat_message_id)
    session.add(log)
    await session.flush()
    result = SaveResult(log=log, urgent=severity == "urgent")

    if category == "allergy":
        sub = structured.get("substance") or narrative[:80]
        session.add(Allergy(patient_id=patient.id, substance=sub, reaction=structured.get("reaction", narrative),
                            verification="pending", reported_by=user.full_name))
        session.add(Alert(patient_id=patient.id, kind="verification", signal="allergy",
                          summary=f"Verify reported allergy: {sub}", evidence=[{"date": observed_at.date().isoformat(),
                          "caretaker": user.full_name.split()[0], "text": narrative}]))

    if category == "medication" and structured.get("status") == "given" and structured.get("medication_id"):
        result.todo_marked = await _mark_med_todo(session, memory, user, patient, structured)

    text, ctx = log_fact(patient, log, user)
    meta = {"log_id": log.id, "category": category, "caretaker_id": user.id, "caretaker_name": user.full_name.split()[0],
            "severity": severity, "medication_id": structured.get("medication_id", ""), "brief": narrative[:160]}
    if category == "allergy":
        meta["verification"] = "pending"
    pat = derive_pattern(category, structured, narrative)
    if pat:
        meta.update(pattern=pat[0], pattern_text=pat[1], pattern_kind=pat[2])
        from app.orchestrator.hints import invalidate

        await invalidate(patient)
    await memory.retain_fact(patient, text=text, occurred_at=observed_at, context=ctx, source_type="care_log",
                             source_id=log.id, metadata=meta, session=session)

    if severity == "urgent":
        a = Alert(patient_id=patient.id, kind="urgent_log", signal="urgent", summary=f"Urgent sign reported: {narrative}",
                  evidence=[{"date": observed_at.date().isoformat(), "caretaker": user.full_name.split()[0], "text": narrative}])
        session.add(a)
        result.new_alerts.append(a)
    await session.commit()

    from app.learning.what_worked import suggest_for_log
    from app.trends.watch import scan_patient

    result.new_alerts += await scan_patient(session, memory, patient)
    if severity == "watch" and category in ("mood", "sleep", "diet"):
        result.suggestion = await suggest_for_log(session, memory, patient, user, log)
    await events.publish(f"user:{user.id}", {"type": "board_changed"})
    return result


async def _mark_med_todo(session, memory, user, patient, structured) -> Todo | None:
    med = await session.get(Medication, uuid.UUID(str(structured["medication_id"]))) if structured.get("medication_id") else None
    if not med:
        return None
    from app.models import TodoTemplate

    rows = await session.scalars(
        select(Todo).join(TodoTemplate, Todo.template_id == TodoTemplate.id).where(
            Todo.patient_id == patient.id, Todo.due_date == today(), TodoTemplate.medication_id == med.id,
            Todo.status.in_(["todo", "in_progress"]),
        ).order_by(Todo.due_time)
    )
    cand = list(rows)
    if not cand:
        return None
    t = cand[0]
    t_hint = structured.get("time")
    if t_hint:
        for c in cand:
            if c.due_time.strftime("%H:%M")[:2] == str(t_hint)[:2]:
                t = c
    await todo_svc.set_status(session, memory, user, t, "done", f"Given: {med.name}")
    return t
