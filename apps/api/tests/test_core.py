import pytest

from app import guard
from app.agent.tools import TOOLS
from tests.conftest import chat

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def pid(c, name):
    r = await c.get("/patients")
    return next(p["id"] for p in r.json() if p["name"].startswith(name))


async def test_unassigned_gets_403(rohan, anjali, client):
    suresh = await pid(anjali, "Suresh")
    assert (await rohan.get(f"/patients/{suresh}")).status_code == 403
    assert (await rohan.get(f"/patients/{suresh}/memory")).status_code == 403
    assert (await rohan.post("/chat", json={"message": "hi", "patient_id": suresh})).status_code == 403
    assert (await anjali.get(f"/patients/{suresh}")).status_code == 200
    assert (await client.get("/patients")).status_code == 401


async def test_no_medication_write_tool():
    assert not [n for n in TOOLS if "medic" in n or "dose" in n]
    assert set(TOOLS) == {"list_todos", "update_todo_status", "log_care", "report_allergy", "recall_memory", "ask_memory",
                          "what_worked", "propose_reschedule", "raise_escalation", "get_patient_profile"}


async def test_pending_meds_never_produce_todos(anjali):
    b = (await anjali.get("/me/board")).json()
    titles = [c["title"] for col in b["columns"] for c in col["cards"]]
    assert not any("Amlodipine" in t for t in titles)
    assert any("Metformin" in t for t in titles) and any("Donepezil" in t for t in titles)


def test_guard_blocks_dose_and_diagnosis():
    assert guard.check_input("Should I increase her metformin dose?").blocked
    assert guard.check_input("what disease does she have, can you diagnose")
    t, _, v = guard.check_output("You should increase the dose to 1000 mg.", [])
    assert v and "dose" in v and "can't advise" in t
    t, cards, v = guard.check_output("ok", [{"type": "suggestion", "evidence": []}])
    assert not cards and "uncited_suggestion" in v
    assert guard.check_input("Asha fell in the bathroom").urgent


async def test_dose_question_refused_in_chat(anjali):
    r = await chat(anjali, message="Should I double Asha's metformin dose?")
    assert "can't advise" in r["text"]


async def test_board_explains_patel_lunch(anjali):
    b = (await anjali.get("/me/board")).json()
    lunch = next(c for col in b["columns"] for c in col["cards"] if c["title"] == "Serve lunch")
    assert "anxious if lunch is late" in lunch["reason"] and "observed" in lunch["memory_chip"]
