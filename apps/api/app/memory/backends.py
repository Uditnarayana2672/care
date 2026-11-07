"""Backends behind MemoryService. Only this package imports hindsight_client."""
import logging
import re
import uuid
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy import select

from app.core.db import SessionLocal
from app.memory.prompts import DIRECTIVES, DISPOSITION, MENTAL_MODELS, MISSION
from app.memory.types import MemoryItem, ReflectAnswer, RetainRequest
from app.models import LocalMemory

log = logging.getLogger(__name__)


class Backend(Protocol):
    name: str

    async def ensure_bank(self, bank_id: str, name: str) -> None: ...
    async def retain(self, bank_id: str, req: RetainRequest) -> None: ...
    async def retain_batch(self, bank_id: str, reqs: list[RetainRequest]) -> None: ...
    async def recall(self, bank_id: str, query: str, types: list[str] | None, max_tokens: int, budget: str) -> list[MemoryItem]: ...
    async def reflect(self, bank_id: str, question: str, context: str | None, budget: str) -> ReflectAnswer: ...
    async def list_recent(self, bank_id: str, limit: int) -> list[MemoryItem]: ...
    async def refresh_mental_models(self, bank_id: str) -> None: ...
    async def delete_bank(self, bank_id: str) -> None: ...


def _item_from_meta(id_: str, text: str, type_: str, when: datetime | None, meta: dict[str, Any], context: str, doc: str) -> MemoryItem:
    st, _, sid = (doc or "").partition(":")
    return MemoryItem(
        id=id_, text=text, type=type_, occurred_at=when,
        caretaker_name=str(meta.get("caretaker_name", "")),
        source_type=str(meta.get("source_type", st)), source_id=str(meta.get("source_id", sid)),
        context=context or "", category=str(meta.get("category", "")), brief=str(meta.get("brief", "")),
    )


# ---------------------------------------------------------------- Hindsight Cloud
class HindsightBackend:
    name = "hindsight"

    def __init__(self, base_url: str, api_key: str):
        from hindsight_client import Hindsight

        self.client = Hindsight(base_url=base_url, api_key=api_key or None, timeout=60.0)

    async def ensure_bank(self, bank_id: str, name: str) -> None:
        c = self.client
        await c.acreate_bank(bank_id=bank_id, name=name, mission=MISSION, disposition=DISPOSITION)
        for n, content in DIRECTIVES:
            try:
                await c.acreate_directive(bank_id=bank_id, name=n, content=content, priority=10)
            except Exception as e:  # noqa: BLE001
                log.warning("directive %s: %s", n, e)
        for mid, q in MENTAL_MODELS:
            try:
                await c.acreate_mental_model(bank_id=bank_id, name=mid, source_query=q, id=mid)
            except Exception as e:  # noqa: BLE001
                log.warning("mental model %s: %s", mid, e)

    async def retain(self, bank_id: str, r: RetainRequest) -> None:
        await self.client.aretain(
            bank_id=bank_id, content=r.text, timestamp=r.occurred_at, context=r.context,
            document_id=r.document_id, metadata=r.metadata,
        )

    async def retain_batch(self, bank_id: str, reqs: list[RetainRequest]) -> None:
        items = [
            {"content": r.text, "timestamp": r.occurred_at, "context": r.context,
             "document_id": r.document_id, "metadata": r.metadata}
            for r in reqs
        ]
        await self.client.aretain_batch(bank_id=bank_id, items=items)

    @staticmethod
    def _conv(r: Any) -> MemoryItem:
        if isinstance(r, dict):  # list_memories returns plain dicts
            from types import SimpleNamespace

            r = SimpleNamespace(**{"id": "", "text": "", "type": "", "context": "", "document_id": "", "metadata": {},
                                   "occurred_start": r.get("event_date") or r.get("occurred_start"), **r})
        meta = getattr(r, "metadata", None) or {}
        when = getattr(r, "occurred_start", None) or getattr(r, "mentioned_at", None)
        if isinstance(when, str):
            when = datetime.fromisoformat(when.replace("Z", "+00:00"))
        return _item_from_meta(
            str(r.id), r.text, getattr(r, "type", "") or "experience", when, meta,
            getattr(r, "context", "") or "", getattr(r, "document_id", "") or "",
        )

    async def recall(self, bank_id, query, types, max_tokens, budget):
        res = await self.client.arecall(bank_id=bank_id, query=query, types=types, max_tokens=max_tokens, budget=budget)
        return [self._conv(r) for r in res.results]

    async def reflect(self, bank_id, question, context, budget):
        ans = await self.client.areflect(bank_id=bank_id, query=question, context=context, budget=budget, include_facts=True)
        facts = getattr(ans, "based_on", None)
        items: list[MemoryItem] = []
        if facts is not None:
            for key in ("memories", "observations", "mental_models"):
                for f in (getattr(facts, key, None) or []):
                    items.append(self._conv(f))
        return ReflectAnswer(text=ans.text, items=items)

    async def list_recent(self, bank_id: str, limit: int) -> list[MemoryItem]:
        res = await self.client.alist_memories(bank_id=bank_id, limit=limit)
        items = [self._conv(r) for r in (getattr(res, "items", None) or [])]
        return sorted(items, key=lambda i: i.occurred_at or datetime.min.replace(tzinfo=UTC), reverse=True)

    async def refresh_mental_models(self, bank_id: str) -> None:
        for mid, _ in MENTAL_MODELS:
            try:
                await self.client.arefresh_mental_model(bank_id=bank_id, mental_model_id=mid)
            except Exception as e:  # noqa: BLE001
                log.warning("refresh %s: %s", mid, e)

    async def delete_bank(self, bank_id: str) -> None:
        try:
            await self.client.banks.delete_bank(bank_id)
        except Exception as e:  # noqa: BLE001
            log.info("delete_bank %s: %s", bank_id, e)


# ---------------------------------------------------------------- Local (offline) backend
_STOP = set("the a an and or of to in on at is was for with she he her his it that this what did do does how any like usually tonight today who when why please tell about".split())


def _tokens(s: str) -> set[str]:
    return {w.rstrip("s") for w in re.findall(r"[a-z0-9]+", s.lower()) if w not in _STOP and len(w) > 2}


class LocalBackend:
    """Stores facts in `local_memory`; consolidates observations from `pattern` metadata."""

    name = "local"

    async def ensure_bank(self, bank_id: str, name: str) -> None:
        return None

    async def retain(self, bank_id: str, r: RetainRequest) -> None:
        await self.retain_batch(bank_id, [r])

    async def retain_batch(self, bank_id: str, reqs: list[RetainRequest]) -> None:
        async with SessionLocal() as s:
            for r in reqs:
                # idempotent per document_id (Hindsight upserts by document)
                existing = await s.scalar(
                    select(LocalMemory).where(LocalMemory.bank_id == bank_id, LocalMemory.document_id == r.document_id)
                )
                if existing:
                    existing.text, existing.occurred_at, existing.meta = r.text, r.occurred_at, dict(r.metadata)
                else:
                    s.add(LocalMemory(bank_id=bank_id, text=r.text, context=r.context, document_id=r.document_id,
                                      occurred_at=r.occurred_at, meta=dict(r.metadata)))
            await s.commit()

    async def _facts(self, bank_id: str) -> list[LocalMemory]:
        async with SessionLocal() as s:
            rows = await s.scalars(
                select(LocalMemory).where(LocalMemory.bank_id == bank_id).order_by(LocalMemory.occurred_at.desc())
            )
            return list(rows)

    @staticmethod
    def _fact_item(m: LocalMemory) -> MemoryItem:
        when = m.occurred_at if m.occurred_at.tzinfo else m.occurred_at.replace(tzinfo=UTC)
        return _item_from_meta(str(m.id), m.text, "experience", when, m.meta or {}, m.context, m.document_id)

    async def observations(self, bank_id: str) -> list[MemoryItem]:
        groups: dict[str, list[LocalMemory]] = {}
        for m in await self._facts(bank_id):
            k = (m.meta or {}).get("pattern")
            if k:
                groups.setdefault(k, []).append(m)
        out = []
        for k, ms in groups.items():
            outcome_ms = [m for m in ms if (m.meta or {}).get("polarity") != "success"]
            if len(outcome_ms) < 2:
                continue
            latest = ms[0]
            ev = [self._fact_item(m) for m in ms]
            out.append(MemoryItem(
                id=f"obs:{k}", text=(latest.meta or {}).get("pattern_text", k), type="observation",
                occurred_at=ev[0].occurred_at, pattern_kind=(latest.meta or {}).get("pattern_kind", ""),
                category=(latest.meta or {}).get("category", ""), proof_count=len(outcome_ms), evidence=ev,
                context="observation",
            ))
        return sorted(out, key=lambda o: -o.proof_count)

    async def recall(self, bank_id, query, types, max_tokens, budget):
        q = _tokens(query)
        want_obs = types is None or "observation" in types
        want_facts = types is None or any(t in types for t in ("world", "experience"))
        scored: list[tuple[float, MemoryItem]] = []
        if want_obs:
            for o in await self.observations(bank_id):
                text_tokens = _tokens(o.text + " " + o.pattern_kind + " " + o.category + " " + " ".join(e.text for e in o.evidence))
                scored.append((len(q & text_tokens) * 1.5 + o.proof_count * 0.1, o))
        if want_facts:
            facts = await self._facts(bank_id)
            for i, m in enumerate(facts):
                it = self._fact_item(m)
                overlap = len(q & _tokens(m.text + " " + m.context + " " + str((m.meta or {}).get("category", ""))))
                scored.append((overlap - i * 0.002, it))
        hits = [(s, it) for s, it in scored if s >= 1] if q else scored
        hits.sort(key=lambda x: -x[0])
        return [it for _, it in hits[: max(5, max_tokens // 150)]]

    async def list_recent(self, bank_id: str, limit: int) -> list[MemoryItem]:
        return [self._fact_item(m) for m in (await self._facts(bank_id))[:limit]]

    async def reflect(self, bank_id, question, context, budget):
        items = await self.recall(bank_id, question + " " + (context or ""), None, 2048, budget)
        if not items:
            return ReflectAnswer(text="Not enough information in memory to answer this.", items=[])
        lines = [f"- {i.text}" for i in items[:8]]
        return ReflectAnswer(text="From memory:\n" + "\n".join(lines), items=items[:8])

    async def refresh_mental_models(self, bank_id: str) -> None:
        return None

    async def delete_bank(self, bank_id: str) -> None:
        from sqlalchemy import delete

        async with SessionLocal() as s:
            await s.execute(delete(LocalMemory).where(LocalMemory.bank_id == bank_id))
            await s.commit()


def make_backend(settings) -> Backend:
    if settings.hindsight_api_key:
        return HindsightBackend(settings.hindsight_base_url, settings.hindsight_api_key)
    return LocalBackend()


__all__ = ["Backend", "HindsightBackend", "LocalBackend", "make_backend", "uuid"]
