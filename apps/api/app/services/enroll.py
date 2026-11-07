import random
import re
from datetime import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.time import now
from app.memory.service import MemoryService
from app.models import (
    Alert,
    Allergy,
    Condition,
    Medication,
    Organization,
    Patient,
    PatientContact,
    Routine,
    User,
)
from app.schemas import EnrollmentIn

COLORS = ["#c2643f", "#1f6f68", "#5b55a6", "#b7801b", "#b2434b"]
TIMES = {"morning": "08:00", "afternoon": "14:00", "night": "20:00"}


def _t(s: str) -> time:
    h, m = s.split(":")[:2]
    return time(int(h), int(m))


async def get_org(session: AsyncSession) -> Organization:
    org = await session.scalar(select(Organization).where(Organization.slug == get_settings().org_slug))
    if not org:
        org = Organization(slug=get_settings().org_slug, name="Demo Care Org")
        session.add(org)
        await session.flush()
    return org


async def new_code(session: AsyncSession) -> str:
    while True:
        code = f"CB-{random.randint(1000, 9999)}"
        if not await session.scalar(select(Patient.id).where(Patient.code == code)):
            return code


async def enroll(session: AsyncSession, memory: MemoryService, data: EnrollmentIn, by: User | None) -> Patient:
    staff = by is not None and by.role in ("coordinator", "admin")
    ver = "verified" if staff else "pending"
    org = await get_org(session)
    count = len(list(await session.scalars(select(Patient.id))))
    p = Patient(org_id=org.id, code=await new_code(session), full_name=data.full_name.strip(), age=data.age, gender=data.gender,
                preferred_language=data.preferred_language, phone=data.phone, address=data.address,
                mobility_level=data.mobility_level, diet_type=", ".join(data.diet), hearing_vision=data.hearing_vision,
                color=COLORS[count % len(COLORS)], enrollment_source="staff" if staff else data.source)
    session.add(p)
    await session.flush()
    c = data.emergency_contact
    if c.name:
        session.add(PatientContact(patient_id=p.id, name=c.name, relation=c.relation, phone=c.phone))
    for cond in data.conditions:
        session.add(Condition(patient_id=p.id, name=cond))
    for m in data.medications:
        session.add(Medication(patient_id=p.id, name=m.name, strength=m.strength, scheduled_times=[TIMES[t] for t in m.times],
                               verification=ver, verified_by=by.id if staff and by else None, source="enrollment"))
    for a in data.allergies:
        session.add(Allergy(patient_id=p.id, substance=a.substance, reaction=a.reaction, verification=ver, reported_by="enrollment"))
    r = data.routine
    for kind, t, note in [("wake", r.wake, ""), ("meal", r.breakfast, "Breakfast"), ("meal", r.lunch, "Lunch"),
                          ("meal", r.dinner, "Dinner"), ("sleep", r.sleep, "Bedtime routine")]:
        session.add(Routine(patient_id=p.id, kind=kind, preferred_time=_t(t), notes=note))
    if any("walk" in x.lower() for x in r.likes):
        session.add(Routine(patient_id=p.id, kind="walk", preferred_time=time(18, 30), notes="Evening walk"))
    await memory.ensure_bank(p)
    parts = [f"{p.full_name}, {p.age}, {p.gender.lower() or 'gender not given'}. Prefers {p.preferred_language}."]
    if p.mobility_level:
        parts.append(f"Mobility: {p.mobility_level}.")
    if p.diet_type:
        parts.append(f"Diet: {p.diet_type}.")
    parts.append(f"Wakes ~{r.wake}, sleeps ~{r.sleep}." + (f" Likes: {', '.join(r.likes)}." if r.likes else ""))
    await memory.retain_fact(p, text=" ".join(parts), occurred_at=now(), context="enrollment", source_type="enrollment",
                             source_id=p.id, metadata={"category": "enrollment", "caretaker_name": "Enrollment"}, session=session)
    if not staff and (data.medications or data.allergies):
        session.add(Alert(patient_id=p.id, kind="verification", signal="verify", summary=f"Verify medical data for {p.full_name}",
                          evidence=[{"date": now().date().isoformat(), "caretaker": "Self-enrollment", "text": "Medicines and allergies pending"}]))
    await session.commit()
    return p


def slug(s: str) -> str:
    return re.sub(r"\W+", "-", s.lower()).strip("-")
