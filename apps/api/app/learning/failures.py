"""W7 — learn why todos fail; propose a reschedule (never for medication)."""
import re
import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import aware, now
from app.memory.service import MemoryService
from app.models import Patient, Suggestion, Todo, TodoEvent, User


@dataclass
class FailureOutcome:
    suggestion: Suggestion | None = None
    coordinator_hint: str | None = None


def _ev(item) -> dict:
    from app.services.facts import evidence_line

    return evidence_line(item)


async def evaluate_failures(session: AsyncSession, memory: MemoryService, patient: Patient, todo: Todo) -> FailureOutcome:
    if not todo.template_id:
        return FailureOutcome()
    since = now() - timedelta(days=7)
    fails = list(await session.scalars(
        select(TodoEvent).join(Todo, TodoEvent.todo_id == Todo.id).where(
            Todo.template_id == todo.template_id, TodoEvent.to_status.in_(["not_done", "skipped"]), TodoEvent.at >= since)
    ))
    if len(fails) < 2:
        return FailureOutcome()
    if todo.category == "medication":
        return FailureOutcome(coordinator_hint=(
            f"'{todo.title}' was not given {len(fails)} times this week. Please discuss timing with the coordinator or doctor; "
            "I can't change medication timing."))
    existing = await session.scalar(select(Suggestion).where(
        Suggestion.patient_id == patient.id, Suggestion.kind == "reschedule", Suggestion.status == "proposed",
        Suggestion.params["template_id"].as_string() == str(todo.template_id)))
    if existing:
        return FailureOutcome(suggestion=existing)
    if not memory.enabled:
        return FailureOutcome()
    # Memory: why does it fail / when does it succeed?
    why = await memory.recall(patient, f"why was {todo.title} not done", types=["observation", "world", "experience"])
    when_ok = await memory.recall(patient, f"when does {todo.title} succeed done", types=["world", "experience"])
    title_l = todo.title.lower()
    seen, fail_items = set(), []
    for i in sorted(why, key=lambda x: aware(x.occurred_at) if x.occurred_at else now(), reverse=True):
        if i.type != "observation" and i.id not in seen and title_l in i.text.lower() and "NOT DONE" in i.text.upper():
            seen.add(i.id)
            fail_items.append(i)
    fail_ev = [_ev(i) for i in fail_items[:4]]
    ok_items = [i for i in when_ok if title_l in i.text.lower() and " DONE" in i.text and "NOT DONE" not in i.text.upper()
                and i.occurred_at]
    ok_items.sort(key=lambda i: aware(i.occurred_at), reverse=True)
    if len(fail_ev) < 2 or not ok_items:
        return FailureOutcome()
    best = ok_items[0]
    local = aware(best.occurred_at).astimezone(memory_tz())
    new_time = local.strftime("%H:%M")
    if new_time == todo.due_time.strftime("%H:%M"):
        return FailureOutcome()
    pretty = local.strftime("%-I:%M %p").lstrip("0")
    reason_txt = _common_reason(fails)
    ev = fail_ev + [_ev(best)]
    s = Suggestion(
        patient_id=patient.id, kind="reschedule", title=f"Move {patient.full_name.split()[0]}'s {todo.title.lower()} to {pretty}?",
        text=(f"{todo.title} for {patient.full_name.split()[0]} was not done {len(fails)} times in the last 7 days"
              f"{' (' + reason_txt + ')' if reason_txt else ''}. It went fine at {pretty} on {local.day} {local.strftime('%b')}."),
        evidence=ev, params={"template_id": str(todo.template_id), "new_time": new_time, "todo_id": str(todo.id)})
    session.add(s)
    await session.commit()
    return FailureOutcome(suggestion=s)


def _common_reason(fails: list[TodoEvent]) -> str:
    reasons = [re.sub(r"\s+", " ", (f.reason or "").lower()).strip() for f in fails if f.reason]
    return max(set(reasons), key=reasons.count) if reasons else ""


def memory_tz():
    from app.core.config import get_settings

    return get_settings().tz


async def decide(session: AsyncSession, memory: MemoryService, user: User, s: Suggestion, accept: bool) -> Suggestion:
    """Accept/dismiss a reschedule or what_worked suggestion and retain the decision."""
    from app.core.time import today
    from app.models import TodoTemplate

    patient = await session.get(Patient, s.patient_id)
    assert patient
    name = user.full_name.split()[0]
    if s.status != "proposed":
        return s
    s.status = "accepted" if accept else "dismissed"
    s.params = {**s.params, "decided_by": name, "decided_at": now().isoformat()}
    if s.kind == "reschedule":
        tpl = await session.get(TodoTemplate, uuid.UUID(s.params["template_id"])) if s.params.get("template_id") else None
        if tpl and accept:
            from datetime import time as dtime

            h, m = (int(x) for x in s.params["new_time"].split(":"))
            tpl.default_time = dtime(h, m)
            tpl.source = "agent_proposal"
            tpl.note = f"Moved by {name} because: {s.text}"
            t = await session.scalar(select(Todo).where(Todo.template_id == tpl.id, Todo.due_date == today(),
                                                          Todo.status.in_(["todo", "in_progress"])))
            if t:
                t.due_time = tpl.default_time
        txt = (f"On {now().astimezone(memory_tz()).strftime('%-d %b %Y')}, caretaker {name} "
               f"{'accepted moving' if accept else 'declined moving'} '{tpl.title if tpl else 'a task'}' to {s.params.get('new_time')}. "
               f"Context: {s.text}")
    else:
        txt = f"Caretaker {name} {'tried' if accept else 'chose not to try'}: {s.title}. Evidence offered: {len(s.evidence)} earlier occurrences."
    await memory.retain_fact(patient, text=txt, occurred_at=now(), context="suggestion_decision",
                             source_type="suggestion", source_id=s.id,
                             metadata={"category": "decision", "caretaker_name": name, "status": s.status}, session=session)
    await session.commit()
    return s
