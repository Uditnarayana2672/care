import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.memory.service import MemoryService
from app.memory.types import MemoryItem
from app.models import Patient, User


@dataclass
class Ctx:
    session: AsyncSession
    user: User
    memory: MemoryService
    patients: dict[uuid.UUID, Patient]
    active: Patient | None = None
    cards: list[dict] = field(default_factory=list)
    quick: list[dict] = field(default_factory=list)
    used: dict[str, MemoryItem] = field(default_factory=dict)
    seen: dict[str, MemoryItem] = field(default_factory=dict)
    drafts: list[dict] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)
    board_changed: bool = False
    escalated: bool = False
    notes: list[str] = field(default_factory=list)

    def card(self, c: dict) -> None:
        self.cards.append(c)

    def qr(self, label: str, action: str, **payload: Any) -> None:
        self.quick.append({"label": label, "action": action, "payload": payload})

    def use(self, items: list[MemoryItem]) -> None:
        for i in items:
            self.used[i.id] = i
            self.seen[i.id] = i
            for e in i.evidence:
                self.seen[e.id] = e

    def patient(self, pid: uuid.UUID | str | None) -> Patient:
        if pid:
            p = self.patients.get(uuid.UUID(str(pid)))
            if not p:
                raise PermissionError("Patient is not in your assignments")
            return p
        if self.active:
            return self.active
        raise LookupError("patient_required")

    def first(self, p: Patient) -> str:
        return p.full_name.split()[0]
