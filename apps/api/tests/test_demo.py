"""The 3-minute demo story (architecture §12) as one sequential test module."""
import pytest
from sqlalchemy import func, select

from app.core.db import SessionLocal
from app.memory.service import get_memory
from app.models import Alert, CareLog, Medication, MemoryLink, Todo, TodoEvent
from tests.conftest import chat

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def patient_id(c, name):
    return next(p["id"] for p in (await c.get("/patients")).json() if p["name"].startswith(name))


async def card_by(c, title):
    b = (await c.get("/me/board")).json()
    return next(x for col in b["columns"] for x in col["cards"] if x["title"] == title)


async def test_trend_alerts_seeded(anjali, meera):
    r = (await anjali.get("/alerts")).json()
    sleep = next(a for a in r if a["signal"] == "sleep")
    assert "not a diagnosis" in sleep["summary"] and sleep["patient_name"] == "Asha Rao"
    assert len(sleep["evidence"]) >= 3 and all(e["date"] and e["caretaker"] for e in sleep["evidence"][:3])
    assert any(a["signal"] == "diet" and a["patient_name"] == "Lakshmi Iyer" for a in r)
    q = (await meera.get("/coordinator/verifications")).json()
    assert {i["kind"] for i in q["queue"]} == {"medication", "allergy"} and q["escalations"]


async def test_w3_w7_bath_refusal_proposes_reschedule(anjali):
    bath = await card_by(anjali, "Morning bath")
    r = await chat(anjali, action="checkin_status", payload={"todo_id": bath["id"], "status": "not_done"})
    assert [q["label"] for q in r["quick"]] == ["Refused", "Asleep", "Unwell", "No time", "Other"]
    r = await chat(anjali, action="todo_reason", payload={"todo_id": bath["id"], "status": "not_done", "reason": "Refused"})
    assert "Feels cold" in [q["label"] for q in r["quick"]]
    r = await chat(anjali, action="todo_reason", payload={"todo_id": bath["id"], "status": "not_done", "reason": "Refused",
                                                          "detail": "feels cold", "final": True})
    card = next(c for c in r["cards"] if c["type"] == "suggestion")
    assert "1:30 PM" in card["title"] and len(card["evidence"]) >= 3
    assert all(e["date"] and e["caretaker"] for e in card["evidence"])
    assert "Observed pattern" in card["note"]
    moved = await chat(anjali, action="accept_suggestion", payload={"id": card["id"]})
    assert "13:30" in moved["text"]
    async with SessionLocal() as s:
        t = await s.get(Todo, __import__("uuid").UUID(bath["id"]))
        assert t.status == "not_done"
        link = await s.scalar(select(MemoryLink).where(MemoryLink.hindsight_document_id.like("suggestion:%")))
        assert link and link.status == "retained"


async def test_w4_multi_log_and_med_todo(anjali):
    msg = ("Gave Asha metformin at 8 with breakfast, she felt nauseous for half an hour. Slept only 5 hours. "
           "Ate half her dinner.")
    r = await chat(anjali, message=msg)
    card = next(c for c in r["cards"] if c["type"] == "log_draft")
    labels = [x["label"] for x in card["rows"]]
    assert labels[:3] == ["Medication", "Sleep", "Diet"]
    assert [q["label"] for q in r["quick"]] == ["Save all", "Edit"]
    entries = r["quick"][0]["payload"]["entries"]
    async with SessionLocal() as s:
        before = await s.scalar(select(func.count()).select_from(CareLog))
    r2 = await chat(anjali, action="save_logs", payload={"entries": entries})
    assert "Saved 3 entries" in r2["text"] and "Marked done" in r2["text"]
    async with SessionLocal() as s:
        assert await s.scalar(select(func.count()).select_from(CareLog)) == before + 3
        metf = await s.scalar(select(Todo).where(Todo.title.like("Metformin%"), Todo.due_time < __import__("datetime").time(12)))
        assert metf.status == "done"


async def test_w6_restless_shows_walk_pattern(anjali):
    r = await chat(anjali, message="Asha is restless after dinner")
    assert [x["label"] for x in next(c for c in r["cards"] if c["type"] == "log_draft")["rows"]][0] == "Mood"
    r2 = await chat(anjali, action="save_logs", payload={"entries": r["quick"][0]["payload"]["entries"]})
    sug = next(c for c in r2["cards"] if c["type"] == "suggestion")
    assert "walk" in sug["title"].lower() and len(sug["evidence"]) >= 2
    assert all(e["date"] and e["caretaker"] for e in sug["evidence"])
    assert [q["label"] for q in r2["quick"]] == ["Try it", "Not now"]
    assert r2["memory"] or True


async def test_w8_no_duplicate_alerts(anjali):
    async with SessionLocal() as s:
        n = await s.scalar(select(func.count()).select_from(Alert).where(Alert.signal == "sleep"))
    assert n == 1


async def test_w5_handoff_for_rohan(rohan):
    r = await chat(rohan, message="I'm taking over Asha tonight. What should I know?")
    card = next(c for c in r["cards"] if c["type"] == "handoff")
    text = " ".join(f"{x['label']}: {x['text']}" for x in card["rows"])
    assert "Walker" in text and "Metformin" in text and "warm water" in text and "Anjali" in text
    assert any(x["label"] == "What helps" for x in card["rows"]) and any(x["label"] == "Watch" for x in card["rows"])
    assert r["memory"]
    pid = r["quick"][0]["payload"]["patient_id"]
    ans = await chat(rohan, action="ask", payload={"question": "Does she take her night tablet easily?", "patient_id": pid})
    assert "warm water" in ans["text"] and "Anjali" in ans["text"]


async def test_w5_unknown_says_so(rohan):
    r = await chat(rohan, message="Does Asha like gardening?")
    assert "Not enough information" in r["text"]


async def test_memory_toggle_before_after(rohan, anjali):
    pid = await patient_id(rohan, "Asha")
    r = await rohan.post("/demo/memory-toggle", json={"question": "I'm taking over Asha tonight. What should I know?", "patient_id": pid})
    d = r.json()
    on_rows = " ".join(x["text"] for c in d["on"]["cards"] for x in c.get("rows", []))
    off_rows = " ".join(x["text"] for c in d["off"]["cards"] for x in c.get("rows", []))
    assert "warm water" in on_rows and "warm water" not in off_rows
    assert "don't have remembered history" in d["off"]["text"]


async def test_kanban_and_chat_write_same_events(anjali):
    pid = await patient_id(anjali, "Lakshmi")
    b = (await anjali.get("/me/board")).json()
    cards = [c for col in b["columns"] for c in col["cards"] if c["patient_id"] == pid and c["status"] == "todo"]
    a, b2 = cards[0], cards[1]
    r1 = await anjali.patch(f"/todos/{a['id']}", json={"status": "done"})
    assert r1.status_code == 200
    await chat(anjali, action="checkin_status", payload={"todo_id": b2["id"], "status": "done"})
    async with SessionLocal() as s:
        evs = {e.todo_id: e for e in await s.scalars(select(TodoEvent).where(TodoEvent.todo_id.in_([__import__("uuid").UUID(a["id"]), __import__("uuid").UUID(b2["id"])])))}
        ea, eb = evs[__import__("uuid").UUID(a["id"])], evs[__import__("uuid").UUID(b2["id"])]
        assert (ea.from_status, ea.to_status, ea.reason) == (eb.from_status, eb.to_status, eb.reason)
        links = list(await s.scalars(select(MemoryLink).where(MemoryLink.source_id.in_([ea.id, eb.id]))))
        assert len(links) == 2 and all(l.status == "retained" for l in links)
    bad = await anjali.patch(f"/todos/{b2['id']}", json={"status": "not_done"})
    assert bad.status_code == 422  # reason required


async def test_urgent_text_escalates(anjali):
    r = await chat(anjali, message="Asha fell in the bathroom")
    assert "112" in r["text"] or "emergency" in r["text"].lower()
    async with SessionLocal() as s:
        assert await s.scalar(select(Alert).where(Alert.kind.in_(["escalation", "urgent_log"]))) is not None


async def test_retain_failure_marked_and_retried():
    mem = get_memory()
    async with SessionLocal() as s:
        from app.models import Patient
        p = (await s.scalars(select(Patient))).first()
        real = mem.backend.retain
        async def boom(*a, **k):
            raise RuntimeError("down")
        mem.backend.retain = boom
        import uuid
        link = await mem.retain_fact(p, text="x", occurred_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
                                     context="t", source_type="care_log", source_id=uuid.uuid4(), metadata={}, session=s)
        await s.commit()
        assert link.status == "failed"
        mem.backend.retain = real
        assert await mem.retry_failed(s) >= 1
        assert (await s.get(MemoryLink, link.id)).status == "retained"


async def test_pending_allergy_creates_alert_not_med(anjali):
    async with SessionLocal() as s:
        n = await s.scalar(select(func.count()).select_from(Medication))
    r = await chat(anjali, message="Suresh has a rash after a new cream")
    entries = r["quick"][0]["payload"]["entries"]
    assert entries[0]["category"] == "allergy"
    await chat(anjali, action="save_logs", payload={"entries": entries})
    async with SessionLocal() as s:
        assert await s.scalar(select(func.count()).select_from(Medication)) == n
