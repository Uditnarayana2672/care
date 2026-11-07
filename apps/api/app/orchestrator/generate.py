"""W2 — build today's todos for a patient from verified meds, routines/care plan, accepted suggestions."""
from datetime import date, time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Assignment, Medication, Patient, Routine, Todo, TodoTemplate


def _t(s: str) -> time:
    h, m = s.split(":")[:2]
    return time(int(h), int(m))


async def sync_templates(session: AsyncSession, patient: Patient) -> None:
    """Medication templates exist only for verified medications; deactivate otherwise."""
    meds = list(await session.scalars(select(Medication).where(Medication.patient_id == patient.id)))
    existing = list(await session.scalars(select(TodoTemplate).where(TodoTemplate.patient_id == patient.id,
                                                                     TodoTemplate.source == "medication")))
    for tpl in existing:
        m = next((x for x in meds if x.id == tpl.medication_id), None)
        tpl.active = bool(m and m.verification == "verified")
    have = {(t.medication_id, t.default_time) for t in existing}
    for m in meds:
        if m.verification != "verified":
            continue
        for ts in m.scheduled_times or []:
            if (m.id, _t(ts)) in have:
                continue
            label = "breakfast" if _t(ts) < time(11) else "dinner" if _t(ts) >= time(18) else "lunch"
            session.add(TodoTemplate(patient_id=patient.id, medication_id=m.id, title=f"{m.name} {m.strength} · {label}".replace("  ", " "),
                                     category="medication", source="medication", default_time=_t(ts),
                                     note=m.instruction or ""))
    await session.flush()


async def enrollment_templates(session: AsyncSession, patient: Patient) -> None:
    """Create routine templates from enrollment routines when none exist (idempotent)."""
    has = await session.scalar(select(TodoTemplate.id).where(TodoTemplate.patient_id == patient.id,
                                                             TodoTemplate.source.in_(["routine", "care_plan"])).limit(1))
    if has:
        return
    routines = list(await session.scalars(select(Routine).where(Routine.patient_id == patient.id)))
    titles = {"meal": "Meal", "walk": "Assisted walk", "bath": "Bath", "sleep": "Bedtime routine", "wake": "Morning routine"}
    cats = {"meal": "meal", "walk": "mobility", "bath": "hygiene", "sleep": "other", "wake": "other"}
    for r in routines:
        if r.preferred_time and r.kind in titles:
            session.add(TodoTemplate(patient_id=patient.id, title=r.notes or titles[r.kind], category=cats[r.kind],
                                     source="routine", default_time=r.preferred_time))


async def generate_for_patient(session: AsyncSession, patient: Patient, day: date, caretaker_id=None) -> int:
    await enrollment_templates(session, patient)
    await sync_templates(session, patient)
    tpls = list(await session.scalars(select(TodoTemplate).where(TodoTemplate.patient_id == patient.id, TodoTemplate.active.is_(True))))
    have = {t.template_id for t in await session.scalars(select(Todo).where(Todo.patient_id == patient.id, Todo.due_date == day))}
    n = 0
    for tpl in tpls:
        if tpl.id in have:
            continue
        session.add(Todo(patient_id=patient.id, template_id=tpl.id, caretaker_id=caretaker_id, due_date=day,
                         due_time=tpl.default_time, title=tpl.title, category=tpl.category))
        n += 1
    await session.flush()
    return n


async def generate_for_all(session: AsyncSession, day: date) -> int:
    n = 0
    for p in await session.scalars(select(Patient).where(Patient.status == "active")):
        cu = await session.scalar(select(Assignment.user_id).where(Assignment.patient_id == p.id, Assignment.active.is_(True)))
        n += await generate_for_patient(session, p, day, cu)
    await session.commit()
    return n
