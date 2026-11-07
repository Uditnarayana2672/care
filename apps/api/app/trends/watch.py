"""W8 — deterministic trend rules on PostgreSQL logs vs the patient's own 14-day baseline."""
from datetime import timedelta
from statistics import mean

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import aware, now
from app.memory.service import MemoryService
from app.models import Alert, CareLog, Patient, User

DISCLAIMER = "This is an observation, not a diagnosis. Please inform the coordinator or doctor."
LOW_MOODS = {"low", "anxious", "confused"}
SMALL = {"half", "little", "none"}


def _ev(log: CareLog, who: dict[str, str], text: str) -> dict:
    return {"id": str(log.id), "date": aware(log.observed_at).strftime("%Y-%m-%d"), "caretaker": who.get(str(log.caretaker_id), ""), "text": text}


async def _logs(session, patient, category, days) -> list[CareLog]:
    since = now() - timedelta(days=days)
    rows = await session.scalars(select(CareLog).where(CareLog.patient_id == patient.id, CareLog.category == category,
                                                       CareLog.observed_at >= since).order_by(CareLog.observed_at.desc()))
    return [r for r in rows]


async def detect(session: AsyncSession, patient: Patient) -> list[dict]:
    names = {str(u.id): u.full_name.split()[0] for u in await session.scalars(select(User))}
    found: list[dict] = []

    # Sleep: avg last 3 nights <= baseline - 1.5h
    sleep = [l for l in await _logs(session, patient, "sleep", 21) if (l.structured or {}).get("hours") is not None]
    if len(sleep) >= 8:
        last3, base = sleep[:3], sleep[3:17]
        if len(base) >= 5:
            a3, b = mean(float(l.structured["hours"]) for l in last3), mean(float(l.structured["hours"]) for l in base)
            if a3 <= b - 1.5:
                found.append({"signal": "sleep", "summary": f"Sleep shorter than usual on 3 of the last 3 nights (≈{a3:.0f}h vs ≈{b:.0f}h).",
                              "evidence": [_ev(l, names, f"Slept ~{l.structured['hours']}h") for l in last3]})
    # Diet: >=3 of last 5 meals half portion or less
    diet = (await _logs(session, patient, "diet", 10))[:5]
    if len(diet) >= 5:
        small = [l for l in diet if (l.structured or {}).get("portion") in SMALL]
        if len(small) >= 3:
            found.append({"signal": "diet", "summary": f"Reduced meal intake on {len(small)} of the last 5 days.",
                          "evidence": [_ev(l, names, f"{l.structured.get('meal', 'Meal')}: {l.structured.get('portion')} portion") for l in small]})
    # Mood: >=3 low/anxious/confused logs in 5 days
    mood = [l for l in await _logs(session, patient, "mood", 5) if (l.structured or {}).get("mood") in LOW_MOODS]
    if len(mood) >= 3:
        found.append({"signal": "mood", "summary": f"Low or anxious mood logged {len(mood)} times in 5 days.",
                      "evidence": [_ev(l, names, l.narrative or str(l.structured.get("mood"))) for l in mood]})
    # Medication: >=2 refusals of same medicine in 7 days
    meds: dict[str, list[CareLog]] = {}
    for l in await _logs(session, patient, "medication", 7):
        if (l.structured or {}).get("status") == "refused":
            meds.setdefault(l.structured.get("medication_name", "medicine"), []).append(l)
    for name, ls in meds.items():
        if len(ls) >= 2:
            found.append({"signal": "medication", "summary": f"{name} refused {len(ls)} times this week.",
                          "evidence": [_ev(l, names, l.narrative or "refused") for l in ls]})
    return found


async def scan_patient(session: AsyncSession, memory: MemoryService, patient: Patient) -> list[Alert]:
    created: list[Alert] = []
    for f in await detect(session, patient):
        open_ = await session.scalar(select(Alert).where(Alert.patient_id == patient.id, Alert.kind == "trend",
                                                         Alert.signal == f["signal"], Alert.status != "resolved"))
        if open_:
            continue
        narrative = await memory.recall(patient, f"{f['signal']} last 7 days", max_tokens=600)
        mem_ev = [{"id": m.id, "date": aware(m.occurred_at).strftime("%Y-%m-%d") if m.occurred_at else "",
                   "caretaker": m.caretaker_name, "text": m.text} for m in narrative[:3]]
        alert = Alert(patient_id=patient.id, kind="trend", signal=f["signal"], summary=f"{f['summary']} {DISCLAIMER}",
                      evidence=f["evidence"] + [e for e in mem_ev if e["id"] not in {x['id'] for x in f['evidence']}][:2])
        session.add(alert)
        await session.flush()
        await memory.retain_fact(patient, text=f"{now().astimezone(memory_tz()).strftime('%-d %b %Y')}: trend alert raised — {f['summary']}",
                                 occurred_at=now(), context="alert", source_type="alert", source_id=alert.id,
                                 metadata={"category": "alert", "signal": f["signal"], "caretaker_name": "CareBridge"}, session=session)
        created.append(alert)
    await session.commit()
    return created


def memory_tz():
    from app.core.config import get_settings

    return get_settings().tz


async def acknowledge(session: AsyncSession, memory: MemoryService, user: User, alert: Alert) -> Alert:
    alert.status = "acknowledged" if alert.status == "open" else alert.status
    alert.acknowledged_by = user.id
    patient = await session.get(Patient, alert.patient_id)
    assert patient
    await memory.retain_fact(patient, text=f"{now().astimezone(memory_tz()).strftime('%-d %b %Y %H:%M')}: {user.full_name} acknowledged alert — {alert.summary.split(' This is')[0]}",
                             occurred_at=now(), context="alert", source_type="alert_ack", source_id=alert.id,
                             metadata={"category": "alert_ack", "caretaker_name": user.full_name.split()[0]}, session=session)
    await session.commit()
    return alert
