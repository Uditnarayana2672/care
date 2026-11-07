from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import assigned_patient_ids
from app.core.time import at_local, local_now, now
from app.memory.service import MemoryService
from app.models import Alert, Patient, Todo, TodoTemplate, User
from app.orchestrator.generate import generate_for_patient
from app.orchestrator.hints import get_hints
from app.orchestrator.score import score_todo

COLS = [("now", "Now"), ("next", "Next"), ("later", "Later"), ("done", "Done"), ("not_done", "Not done")]


def initials(name: str) -> str:
    return "".join(w[0] for w in name.split()[:2]).upper()


def fmt_time(t) -> str:
    return t.strftime("%-I:%M %p")


async def build_board(session: AsyncSession, memory: MemoryService, user: User, day: date | None = None) -> dict:
    day = day or local_now().date()
    ids = await assigned_patient_ids(session, user)
    patients = {p.id: p for p in await session.scalars(select(Patient).where(Patient.id.in_(ids), Patient.status == "active"))}
    for p in patients.values():
        if day == local_now().date():
            await generate_for_patient(session, p, day, user.id if user.role == "caretaker" else None)
    await session.commit()
    todos = list(await session.scalars(select(Todo).where(Todo.patient_id.in_(list(patients)), Todo.due_date == day)))
    alerts = list(await session.scalars(select(Alert).where(Alert.patient_id.in_(list(patients)), Alert.status.in_(["open", "acknowledged"]))))
    hints = {pid: await get_hints(memory, p) for pid, p in patients.items()}
    notes = {t.id: t.note for t in await session.scalars(select(TodoTemplate).where(TodoTemplate.patient_id.in_(list(patients))))}
    cols: dict[str, list] = {k: [] for k, _ in COLS}
    t_now = now()
    for t in todos:
        p = patients[t.patient_id]
        sc = score_todo(t, t_now, [a for a in alerts if a.patient_id == t.patient_id and a.status == "open"], hints[t.patient_id], notes.get(t.template_id, ""))
        t.priority_score, t.priority_reason, t.memory_chip = sc.score, sc.reason, sc.chip
        cols[sc.column].append({
            "id": str(t.id), "patient_id": str(p.id), "patient_name": p.full_name, "patient_initials": initials(p.full_name),
            "patient_color": p.color, "title": t.title, "time": fmt_time(t.due_time), "due_time": t.due_time.strftime("%H:%M"),
            "category": t.category, "status": t.status, "reason": sc.reason, "memory_chip": sc.chip, "score": sc.score,
            "overdue": at_local(t.due_date, t.due_time) < t_now and t.status in ("todo", "in_progress"),
        })
    await session.commit()
    for k in ("now", "next", "later"):
        cols[k].sort(key=lambda c: (-c["score"], c["due_time"]))
    for k in ("done", "not_done"):
        cols[k].sort(key=lambda c: c["due_time"])
    return {
        "date": day.isoformat(),
        "columns": [{"key": k, "label": l, "cards": cols[k]} for k, l in COLS],
        "patients": [{"id": str(p.id), "name": p.full_name, "initials": initials(p.full_name), "color": p.color} for p in patients.values()],
        "alerts": [_alert(a, patients[a.patient_id]) for a in alerts if a.status == "open" and a.kind in ("trend", "urgent_log", "missed_med")],
        "stats": {"patients": len(patients), "open": sum(len(cols[k]) for k in ("now", "next", "later")), "done": len(cols["done"])},
    }


def _alert(a: Alert, p: Patient) -> dict:
    return {"id": str(a.id), "patient_id": str(p.id), "patient_name": p.full_name, "kind": a.kind, "signal": a.signal,
            "summary": a.summary, "evidence": a.evidence, "status": a.status, "created_at": a.created_at.isoformat()}
