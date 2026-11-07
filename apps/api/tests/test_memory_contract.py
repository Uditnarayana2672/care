"""Contract tests: MemoryService → HindsightBackend against a fake hindsight client."""
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.memory.backends import HindsightBackend
from app.memory.service import MemoryService, bank_id_for
from app.models import Patient

pytestmark = pytest.mark.asyncio(loop_scope="session")


class FakeClient:
    def __init__(self):
        self.calls = []

    async def acreate_bank(self, **k): self.calls.append(("create_bank", k))
    async def acreate_directive(self, **k): self.calls.append(("directive", k))
    async def acreate_mental_model(self, **k): self.calls.append(("mental_model", k))
    async def aretain(self, **k): self.calls.append(("retain", k))
    async def aretain_batch(self, **k): self.calls.append(("retain_batch", k))
    async def arefresh_mental_model(self, **k): self.calls.append(("refresh", k))

    async def arecall(self, **k):
        self.calls.append(("recall", k))
        return SimpleNamespace(results=[SimpleNamespace(
            id="m1", text="Anjali gave Metformin with warm water", type="experience", context="medication_effect",
            occurred_start=datetime(2026, 11, 6, tzinfo=UTC), mentioned_at=None, document_id="care_log:abc",
            metadata={"caretaker_name": "Anjali", "source_type": "care_log", "source_id": "abc"})])

    async def areflect(self, **k):
        self.calls.append(("reflect", k))
        return SimpleNamespace(text="Answer", based_on=SimpleNamespace(memories=[SimpleNamespace(
            id="m2", text="fact", type="world", context="", occurred_start=None, mentioned_at=None, document_id="todo_event:x",
            metadata={})], observations=[], mental_models=[]))


def make():
    b = HindsightBackend.__new__(HindsightBackend)
    b.client = FakeClient()
    return MemoryService(backend=b, enabled=True), b.client


def patient():
    return Patient(id=uuid.uuid4(), org_id=uuid.uuid4(), code="CB-1", full_name="Test P", age=80)


async def test_bank_config_and_isolation():
    svc, fc = make()
    p = patient()
    bank = await svc.ensure_bank(p)
    assert bank == bank_id_for(p.id) == p.hindsight_bank_id and bank.startswith("cb-")
    kinds = [c[0] for c in fc.calls]
    assert kinds.count("directive") == 4 and kinds.count("mental_model") == 3
    cb = next(c[1] for c in fc.calls if c[0] == "create_bank")
    assert cb["disposition"] == {"skepticism": 4, "literalism": 4, "empathy": 4} and "care memory" in cb["mission"]


async def test_retain_is_attributed_timestamped_and_linked():
    svc, fc = make()
    p = patient()
    sid = uuid.uuid4()
    when = datetime(2026, 11, 6, 8, 0, tzinfo=UTC)
    link = await svc.retain_fact(p, text="6 Nov — Metformin given by Anjali.", occurred_at=when, context="medication_effect",
                                 source_type="care_log", source_id=sid, metadata={"caretaker_name": "Anjali", "category": "medication"})
    k = next(c[1] for c in fc.calls if c[0] == "retain")
    assert k["bank_id"] == bank_id_for(p.id) and k["timestamp"] == when and k["context"] == "medication_effect"
    assert k["document_id"] == f"care_log:{sid}" and k["metadata"]["caretaker_name"] == "Anjali"
    assert k["metadata"]["source_type"] == "care_log" and link.status == "retained"


async def test_recall_exposes_attribution_and_reflect_cites():
    svc, _ = make()
    p = patient()
    items = await svc.recall(p, "warm water")
    assert items[0].caretaker_name == "Anjali" and items[0].source_id == "abc" and items[0].occurred_at
    ans = await svc.reflect(p, "handoff")
    assert ans.text == "Answer" and ans.memory_ids == ["m2"]


async def test_disabled_memory_returns_empty():
    svc, fc = make()
    svc.enabled = False
    assert await svc.recall(patient(), "x") == []
    assert (await svc.reflect(patient(), "x")).items == []
    assert not [c for c in fc.calls if c[0] in ("recall", "reflect")]


@pytest.mark.live
async def test_live_hindsight_roundtrip():  # pytest -m live  (needs HINDSIGHT_API_KEY)
    import os

    if not os.getenv("HINDSIGHT_API_KEY"):
        pytest.skip("no key")
    from app.core.config import get_settings

    svc = MemoryService(backend=HindsightBackend(get_settings().hindsight_base_url, os.environ["HINDSIGHT_API_KEY"]), enabled=True)
    p = patient()
    await svc.ensure_bank(p)
    await svc.retain_fact(p, text="On 6 Nov 2026 caretaker Anjali gave Metformin with warm water.", occurred_at=datetime.now(UTC),
                          context="medication_effect", source_type="care_log", source_id=uuid.uuid4(), metadata={"caretaker_name": "Anjali"})
    assert await svc.recall(p, "warm water")
    await svc.delete_bank(p)
