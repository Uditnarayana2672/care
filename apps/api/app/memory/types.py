import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class MemoryItem(BaseModel):
    id: str
    text: str
    type: str = "experience"  # world | experience | observation
    occurred_at: datetime | None = None
    caretaker_name: str = ""
    source_type: str = ""
    source_id: str = ""
    context: str = ""
    category: str = ""
    brief: str = ""
    pattern_kind: str = ""  # helps | fails | routine | constraint (observations)
    proof_count: int = 0
    evidence: list["MemoryItem"] = Field(default_factory=list)


class ReflectAnswer(BaseModel):
    text: str
    items: list[MemoryItem] = Field(default_factory=list)

    @property
    def memory_ids(self) -> list[str]:
        return [i.id for i in self.items]


class RetainRequest(BaseModel):
    text: str
    occurred_at: datetime
    context: str
    document_id: str
    metadata: dict[str, str] = Field(default_factory=dict)


def doc_id(source_type: str, source_id: uuid.UUID | str) -> str:
    return f"{source_type}:{source_id}"
