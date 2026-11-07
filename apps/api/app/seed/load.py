"""Seed synthetic data: PostgreSQL/SQLite rows + 14 days of history replayed into memory with original timestamps.

    python -m app.seed.load            # load (idempotent: skips if already seeded)
    python -m app.seed.load --reset    # wipe tables + memory banks, reseed
"""
import asyncio
import json
import logging
import sys
import uuid
from datetime import datetime, time, timedelta
from pathlib import Path

from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import Base, SessionLocal, engine
from app.core.time import at_local, today
from app.memory.patterns import derive_pattern, todo_pattern
from app.memory.service import MemoryService, get_memory
from app.memory.types import RetainRequest, doc_id
from app.models import (
    Alert,
    Allergy,
    Assignment,
    CareLog,
    Condition,
    Medication,
    Organization,
    Patient,
    PatientContact,
    Routine,
    Todo,
    TodoEvent,
    TodoTemplate,
    User,
)
from app.orchestrator.generate import generate_for_all
from app.services.facts import log_fact, todo_outcome_fact
from app.trends.watch import scan_patient

log = logging.getLogger("seed")


def seed_dir() -> Path:
    # repo checkout: <root>/apps/api/app/seed/load.py -> <root>/seed; docker: mounted at /seed
    candidates = [p / "seed" for p in Path(__file__).resolve().parents] + [Path("/seed")]
    for c in candidates:
        if (c / "patients.json").exists():
            return c
    raise FileNotFoundError("seed directory not found")


def T(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


class Builder:
    def __init__(self, session, memory: MemoryService, users: dict[str, User], pats: dict[str, Patient]):
        self.s, self.m, self.users, self.pats = session, memory, users, pats
        self.reqs: dict[str, list[RetainRequest]] = {k: [] for k in pats}

    def when(self, offset: int, hhmm: str) -> datetime:
        return at_local(today() + timedelta(days=offset), T(hhmm))

    def add_req(self, key: str, req: RetainRequest) -> None:
        self.reqs[key].append(req)

    async def log(self, key: str, by: str, offset: int, hhmm: str, category: str, structured: dict, narrative: str,
                  severity: str = "normal") -> CareLog:
        p, u = self.pats[key], self.users[by]
        lg = CareLog(patient_id=p.id, caretaker_id=u.id, category=category, structured=structured, narrative=narrative,
                     severity=severity, observed_at=self.when(offset, hhmm))
        self.s.add(lg)
        await self.s.flush()
        text, ctx = log_fact(p, lg, u)
        meta = {"log_id": str(lg.id), "category": category, "caretaker_id": str(u.id), "caretaker_name": u.full_name.split()[0],
                "severity": severity, "source_type": "care_log", "source_id": str(lg.id), "brief": narrative}
        pat = derive_pattern(category, structured, narrative)
        if pat:
            meta.update(pattern=pat[0], pattern_text=pat[1], pattern_kind=pat[2])
        self.add_req(key, RetainRequest(text=text, occurred_at=lg.observed_at, context=ctx, document_id=doc_id("care_log", lg.id), metadata=meta))
        return lg

    async def todo_event(self, key: str, by: str, offset: int, tpl_title: str, status: str, reason: str, at_hhmm: str,
                         due: str) -> None:
        p, u = self.pats[key], self.users[by]
        tpl = await self.s.scalar(select(TodoTemplate).where(TodoTemplate.patient_id == p.id, TodoTemplate.title == tpl_title))
        assert tpl
        day = today() + timedelta(days=offset)
        t = Todo(patient_id=p.id, caretaker_id=u.id, template_id=tpl.id, due_date=day, due_time=T(due), title=tpl.title,
                 category=tpl.category, status=status, status_note=reason, checkin_sent=True)
        self.s.add(t)
        await self.s.flush()
        at = self.when(offset, at_hhmm)
        ev = TodoEvent(todo_id=t.id, actor_id=u.id, from_status="todo", to_status=status, reason=reason, at=at)
        self.s.add(ev)
        await self.s.flush()
        meta = {"todo_id": str(t.id), "category": t.category, "status": status, "caretaker_id": str(u.id),
                "caretaker_name": u.full_name.split()[0], "source_type": "todo_event", "source_id": str(ev.id),
                "brief": f"{t.title}: {status.replace('_', ' ')}" + (f" — {reason}" if reason else "")}
        pat = todo_pattern(t.title, status, reason)
        if pat:
            meta.update(pattern=pat[0], pattern_text=pat[1], pattern_kind=pat[2])
        self.add_req(key, RetainRequest(text=todo_outcome_fact(p, t, u, status, reason, at), occurred_at=at, context="todo_outcome",
                                        document_id=doc_id("todo_event", ev.id), metadata=meta))


async def build_history(b: Builder) -> None:
    A, R = "anjali", "rohan"
    # ---- Asha: sleep (14 nights), baseline ~7h, last 3 nights ~5h
    base = [7, 7.5, 6.5, 7, 7, 7.5, 7, 6.5, 7, 7.5, 7]
    for i, h in enumerate(base):
        off = -14 + i
        who = R if off in (-9, -8, -7, -5, -4) else A
        await b.log("asha", who, off, "07:00", "sleep", {"hours": h, "wake_ups": 1, "quality": "good"}, "Slept well")
    for off, who in ((-3, R), (-2, A), (-1, A)):
        await b.log("asha", who, off, "07:00", "sleep", {"hours": 5, "wake_ups": 2, "quality": "poor"}, "Slept badly, woke twice", "watch")
    # ---- Asha: dinners
    for off in range(-14, 0):
        full = off not in (-1, -6)
        await b.log("asha", A, off, "20:15", "diet", {"meal": "dinner", "portion": "full" if full else "half",
                    "refused_items": "curd" if off == -1 else None}, "Ate dinner" if full else "Ate half of dinner")
    # ---- Asha: metformin (morning daily; evening warm water)
    for off in range(-14, 0):
        who = R if off in (-9, -8, -7, -5, -4) else A
        eff = "mild nausea for ~30 minutes, settled after rest" if off == -1 else None
        meds = b.pats["asha"]
        med = await b.s.scalar(select(Medication).where(Medication.patient_id == meds.id))
        await b.log("asha", who, off, "08:00", "medication",
                    {"medication_id": str(med.id), "medication_name": "Metformin 500 mg", "status": "given", "observed_effects": eff},
                    "Metformin given with breakfast")
    for off in (-3, -1):
        await b.log("asha", A, off, "20:00", "medication", {"medication_name": "Metformin 500 mg", "status": "given"},
                    "Took Metformin easily with warm water after dinner")
    # ---- Asha: restless → walk → calm (3 occurrences)
    await b.log("asha", R, -5, "19:15", "mood", {"mood": "restless", "triggers": "after dinner", "what_helped": "supported walk"},
                "Restless after dinner; supported walk; mood improved and calm after", "watch")
    await b.log("asha", A, -3, "21:00", "mood", {"mood": "anxious", "triggers": "before bed", "what_helped": "short walk"},
                "Anxious before bed; short walk; calmer", "watch")
    await b.log("asha", A, -1, "18:30", "mood", {"mood": "restless", "triggers": "after dinner", "what_helped": "10-minute assisted walk"},
                "Restless after dinner; 10-minute assisted walk; calmed and slept through", "watch")
    # ---- Asha: allergy report (pending)
    await b.log("asha", R, -4, "10:20", "allergy", {"substance": "new soap", "reaction": "rash"}, "Rash after a new soap", "watch")
    b.s.add(Allergy(patient_id=b.pats["asha"].id, substance="New soap", reaction="Rash", verification="pending", reported_by="Rohan Kumar"))
    # ---- Asha: bath outcomes (W7 story)
    for off in range(-8, -3):
        await b.todo_event("asha", A if off != -7 else R, off, "Morning bath", "done", "", "08:20", "08:00")
    await b.todo_event("asha", R, -3, "Morning bath", "not_done", "refused, water felt cold", "08:10", "08:00")
    await b.todo_event("asha", R, -2, "Morning bath", "done", "", "13:30", "08:00")
    await b.todo_event("asha", A, -1, "Morning bath", "not_done", "refused, feels cold, asked for later", "08:10", "08:00")

    # ---- Suresh: late lunch → anxious (4 occurrences, W9 reason)
    for off in (-12, -9, -6, -3):
        await b.log("suresh", A, off, "13:50", "mood", {"mood": "anxious", "triggers": "late lunch"},
                    "Lunch was served late (13:50); became anxious and kept pacing until served", "watch")
    for off in range(-14, 0):
        await b.log("suresh", A, off, "07:00", "sleep", {"hours": 7, "wake_ups": 1, "quality": "fair"}, "Slept fairly")
    # ---- Lakshmi: reduced dinner intake last 5 days
    ports = {-14: "full", -13: "full", -12: "half", -11: "full", -10: "full", -9: "full", -8: "full", -7: "full", -6: "full",
             -5: "half", -4: "little", -3: "full", -2: "half", -1: "half"}
    for off, pt in ports.items():
        await b.log("lakshmi", A, off, "20:00", "diet", {"meal": "dinner", "portion": pt}, f"Dinner {pt} portion", "watch" if pt in ("half", "little") else "normal")


async def run(reset: bool = False) -> None:
    memory = get_memory()
    if reset:
        async with SessionLocal() as s:
            try:
                for p in await s.scalars(select(Patient)):
                    await memory.delete_bank(p)
            except Exception:  # noqa: BLE001
                pass
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    people = json.loads((seed_dir() / "people.json").read_text())
    data = json.loads((seed_dir() / "patients.json").read_text())
    async with SessionLocal() as s:
        if await s.scalar(select(Organization.id).limit(1)):
            log.info("already seeded (use --reset)")
            return
        org = Organization(**people["organization"])
        s.add(org)
        await s.flush()
        users = {}
        for u in people["users"]:
            users[u["full_name"].split()[0].lower()] = User(id=uuid.uuid5(uuid.NAMESPACE_DNS, u["email"]), org_id=org.id, **u)  # stable ids: sessions survive demo-reset
        s.add_all(users.values())
        await s.flush()
        pats: dict[str, Patient] = {}
        for pd in data["patients"]:
            p = Patient(id=uuid.uuid5(uuid.NAMESPACE_DNS, pd["code"]), org_id=org.id, code=pd["code"], full_name=pd["full_name"], age=pd["age"], gender=pd["gender"],
                        preferred_language=pd["preferred_language"], phone=pd["phone"], address=pd["address"], color=pd["color"],
                        mobility_level=pd["mobility_level"], diet_type=pd["diet_type"], enrollment_source="staff")
            s.add(p)
            await s.flush()
            pats[pd["key"]] = p
            s.add(PatientContact(patient_id=p.id, **pd["contact"]))
            s.add_all(Condition(patient_id=p.id, name=c) for c in pd["conditions"])
            for m in pd["medications"]:
                s.add(Medication(patient_id=p.id, name=m["name"], strength=m["strength"], scheduled_times=m["times"],
                                 instruction=m["instruction"], verification=m["verification"], source=m.get("source", "staff"),
                                 verified_by=users["meera"].id if m["verification"] == "verified" else None))
            s.add_all(Allergy(patient_id=p.id, **a) for a in pd["allergies"])
            for kind, t, note in pd["routines"]:
                s.add(Routine(patient_id=p.id, kind=kind, preferred_time=T(t), notes=note))
            for tp in pd["templates"]:
                s.add(TodoTemplate(patient_id=p.id, title=tp["title"], category=tp["category"], source=tp["source"],
                                   default_time=T(tp["time"]), note=tp.get("note", "")))
            for uk in pd["assigned"]:
                s.add(Assignment(patient_id=p.id, user_id=users[uk].id))
            await memory.ensure_bank(p)
        await s.flush()
        await generate_for_all(s, today() - timedelta(days=30))  # materialise medication templates (verified only)
        await s.execute(Todo.__table__.delete())  # discard the throwaway day
        b = Builder(s, memory, users, pats)
        for pd in data["patients"]:
            p = pats[pd["key"]]
            b.add_req(pd["key"], RetainRequest(
                text=f"{p.full_name}, {p.age}, {p.gender.lower()}. Prefers {p.preferred_language}. {p.mobility_level}. Diet: {p.diet_type}.",
                occurred_at=b.when(-14, "09:00"), context="enrollment", document_id=doc_id("enrollment", p.id),
                metadata={"category": "enrollment", "caretaker_name": "Enrollment", "source_type": "enrollment", "source_id": str(p.id)}))
        await build_history(b)
        for key, reqs in b.reqs.items():
            await memory.retain_batch(pats[key], reqs, s)
        await s.commit()
        for p in pats.values():
            await scan_patient(s, memory, p)
        await memory.refresh_mental_models(pats["asha"])
        log.info("seeded %s patients, %s users, alerts: %s", len(pats), len(users), len(list(await s.scalars(select(Alert)))))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run("--reset" in sys.argv))
    print("done · memory backend:", "hindsight" if get_settings().hindsight_api_key else "local")
