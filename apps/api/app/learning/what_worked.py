"""W6 — 'what worked before': observation-backed suggestions with evidence."""
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import aware, now
from app.memory.service import MemoryService
from app.models import CareLog, Patient, Suggestion, User


def _line(i) -> dict:
    from app.services.facts import evidence_line

    return evidence_line(i)


def _conflicts_with_care_plan(patient: Patient, text: str) -> bool:
    mob = (patient.mobility_level or "").lower()
    return "walk" in text.lower() and ("bedbound" in mob or "wheelchair" in mob and "walker" not in mob)


async def what_worked(session: AsyncSession, memory: MemoryService, patient: Patient, situation: str,
                      *, persist: bool = True) -> Suggestion | None:
    obs = await memory.observations(patient, situation or "restless calm helps")
    cutoff = now() - timedelta(days=30)
    for o in obs:
        if o.pattern_kind != "helps":
            continue
        recent = [e for e in o.evidence if e.occurred_at and aware(e.occurred_at) >= cutoff]
        if len(recent) < 2 or not any(e.caretaker_name for e in recent):
            continue
        if _conflicts_with_care_plan(patient, o.text):
            continue
        existing = await session.scalar(select(Suggestion).where(
            Suggestion.patient_id == patient.id, Suggestion.kind == "what_worked", Suggestion.status == "proposed",
            Suggestion.params["obs"].as_string() == o.id))
        if existing:
            return existing
        ev = [_line(e) for e in recent[:4]]
        s = Suggestion(patient_id=patient.id, kind="what_worked",
                       title="Offer a 10-minute assisted evening walk" if "walk" in o.text.lower() else o.text,
                       text=f"Observed pattern — not a clinical instruction. {o.text} ({len(recent)} times in 30 days).",
                       evidence=ev, params={"obs": o.id, "proof": len(recent), "keyword": "walk" if "walk" in o.text.lower() else ""})
        if persist:
            session.add(s)
            await session.commit()
        return s
    return None


async def suggest_for_log(session, memory: MemoryService, patient: Patient, user: User, log: CareLog) -> Suggestion | None:
    situation = f"{log.category} {log.narrative} {' '.join(str(v) for v in (log.structured or {}).values())}"
    return await what_worked(session, memory, patient, situation)
