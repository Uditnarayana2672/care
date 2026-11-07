"""MemoryService: the only entry point to patient memory (Hindsight or local backend)."""
import logging
import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.memory.backends import Backend, LocalBackend, make_backend
from app.memory.types import MemoryItem, ReflectAnswer, RetainRequest, doc_id
from app.models import MemoryLink, Patient

log = logging.getLogger(__name__)


def bank_id_for(patient_id: uuid.UUID) -> str:
    return f"cb-{get_settings().org_slug}-patient-{patient_id}"


class MemoryService:
    def __init__(self, backend: Backend | None = None, enabled: bool | None = None):
        self.backend = backend or make_backend(get_settings())
        self.enabled = get_settings().memory_enabled if enabled is None else enabled

    # ------------------------------------------------------------ banks
    async def ensure_bank(self, patient: Patient) -> str:
        bank = patient.hindsight_bank_id or bank_id_for(patient.id)  # derived server-side only
        try:
            await self.backend.ensure_bank(bank, f"Care memory — {patient.full_name}")
        except Exception:  # noqa: BLE001
            log.exception("ensure_bank failed for %s", bank)
        patient.hindsight_bank_id = bank
        return bank

    def _bank(self, patient: Patient) -> str:
        return patient.hindsight_bank_id or bank_id_for(patient.id)

    # ------------------------------------------------------------ write
    async def retain_fact(
        self, patient: Patient, *, text: str, occurred_at: datetime, context: str,
        source_type: str, source_id: uuid.UUID, metadata: dict, session: AsyncSession | None = None,
    ) -> MemoryLink:
        """Retain a factual, attributed, timestamped sentence. Never raises: failures are recorded."""
        if session is not None:
            await session.commit()  # PostgreSQL is authoritative: persist the source row before retaining
        meta = {k: str(v) for k, v in {**metadata, "source_type": source_type, "source_id": source_id}.items() if v is not None}
        req = RetainRequest(text=text, occurred_at=occurred_at, context=context,
                            document_id=doc_id(source_type, source_id), metadata=meta)
        link = MemoryLink(patient_id=patient.id, source_type=source_type, source_id=source_id,
                          hindsight_document_id=req.document_id, status="pending", payload=req.model_dump(mode="json"))
        try:
            await self.backend.retain(self._bank(patient), req)
            link.status, link.attempts = "retained", 1
        except Exception:  # noqa: BLE001
            log.exception("retain failed for %s", req.document_id)
            link.status, link.attempts = "failed", 1
        if session is not None:
            session.add(link)
        else:
            async with SessionLocal() as s:
                s.add(link)
                await s.commit()
        return link

    async def retain_batch(self, patient: Patient, reqs: list[RetainRequest], session: AsyncSession) -> None:
        await session.commit()
        await self.backend.retain_batch(self._bank(patient), reqs)
        for r in reqs:
            st, _, sid = r.document_id.partition(":")
            session.add(MemoryLink(patient_id=patient.id, source_type=st, source_id=uuid.UUID(sid),
                                   hindsight_document_id=r.document_id, status="retained", payload=r.model_dump(mode="json"), attempts=1))

    async def retry_failed(self, session: AsyncSession, limit: int = 50) -> int:
        from sqlalchemy import select

        rows = await session.scalars(select(MemoryLink).where(MemoryLink.status == "failed", MemoryLink.attempts < 6).limit(limit))
        n = 0
        for link in rows:
            patient = await session.get(Patient, link.patient_id)
            if not patient:
                continue
            try:
                await self.backend.retain(self._bank(patient), RetainRequest(**link.payload))
                link.status = "retained"
                n += 1
            except Exception:  # noqa: BLE001
                link.attempts += 1
        await session.commit()
        return n

    # ------------------------------------------------------------ read
    async def recall(self, patient: Patient, query: str, *, types: list[str] | None = None,
                     max_tokens: int = 2048, budget: str = "mid") -> list[MemoryItem]:
        if not self.enabled:
            return []
        try:
            return await self.backend.recall(self._bank(patient), query, types, max_tokens, budget)
        except Exception:  # noqa: BLE001
            log.exception("recall failed")
            return []

    async def list_recent(self, patient: Patient, limit: int = 60) -> list[MemoryItem]:
        if not self.enabled:
            return []
        try:
            return await self.backend.list_recent(self._bank(patient), limit)
        except Exception:  # noqa: BLE001
            log.exception("list_recent failed")
            return []

    async def observations(self, patient: Patient, query: str = "") -> list[MemoryItem]:
        if not self.enabled:
            return []
        try:
            if isinstance(self.backend, LocalBackend):
                obs = await self.backend.observations(self._bank(patient))
                if query:
                    from app.memory.backends import _tokens

                    q = _tokens(query)
                    scored = [(len(q & _tokens(o.text + " " + o.pattern_kind + o.category)), o) for o in obs]
                    obs = [o for s, o in sorted(scored, key=lambda x: -x[0]) if s > 0] or []
                return obs
            return await self.recall(patient, query or "patterns that help or fail", types=["observation"])
        except Exception:  # noqa: BLE001
            log.exception("observations failed")
            return []

    async def reflect(self, patient: Patient, question: str, *, context: str | None = None,
                      budget: str = "mid") -> ReflectAnswer:
        if not self.enabled:
            return ReflectAnswer(text="", items=[])
        try:
            return await self.backend.reflect(self._bank(patient), question, context, budget)
        except Exception:  # noqa: BLE001
            log.exception("reflect failed")
            return ReflectAnswer(text="", items=[])

    async def refresh_mental_models(self, patient: Patient) -> None:
        try:
            await self.backend.refresh_mental_models(self._bank(patient))
        except Exception:  # noqa: BLE001
            log.exception("refresh_mental_models failed")

    async def delete_bank(self, patient: Patient) -> None:
        await self.backend.delete_bank(self._bank(patient))


_svc: MemoryService | None = None


def get_memory() -> MemoryService:
    global _svc
    if _svc is None:
        _svc = MemoryService()
    return _svc


def set_memory(svc: MemoryService | None) -> None:
    global _svc
    _svc = svc
