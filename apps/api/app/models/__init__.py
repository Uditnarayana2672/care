import uuid
from datetime import UTC, date, datetime, time

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Integer, String, Text, Time, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


def _id() -> uuid.UUID:
    return uuid.uuid4()


def _now() -> datetime:
    return datetime.now(UTC)


class TS:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Organization(Base):
    __tablename__ = "organization"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_id)
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(200))


class User(Base):
    __tablename__ = "user"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_id)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organization.id"))
    email: Mapped[str] = mapped_column(String(200), unique=True)
    full_name: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(20))  # caretaker | coordinator | admin


class Patient(Base):
    __tablename__ = "patient"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_id)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organization.id"))
    code: Mapped[str] = mapped_column(String(20), unique=True)
    full_name: Mapped[str] = mapped_column(String(200))
    age: Mapped[int] = mapped_column(Integer)
    gender: Mapped[str] = mapped_column(String(40), default="")
    preferred_language: Mapped[str] = mapped_column(String(40), default="English")
    phone: Mapped[str] = mapped_column(String(40), default="")
    address: Mapped[str] = mapped_column(Text, default="")
    mobility_level: Mapped[str] = mapped_column(String(60), default="")
    diet_type: Mapped[str] = mapped_column(String(120), default="")
    hearing_vision: Mapped[str] = mapped_column(String(120), default="")
    color: Mapped[str] = mapped_column(String(10), default="#1f6f68")
    hindsight_bank_id: Mapped[str | None] = mapped_column(String(200), unique=True, nullable=True)
    enrollment_source: Mapped[str] = mapped_column(String(20), default="staff")
    status: Mapped[str] = mapped_column(String(20), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class PatientContact(Base):
    __tablename__ = "patient_contact"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_id)
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patient.id"))
    name: Mapped[str] = mapped_column(String(200))
    relation: Mapped[str] = mapped_column(String(80), default="")
    phone: Mapped[str] = mapped_column(String(40), default="")


class Condition(Base):
    __tablename__ = "condition"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_id)
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patient.id"))
    name: Mapped[str] = mapped_column(String(120))


class Allergy(Base):
    __tablename__ = "allergy"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_id)
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patient.id"))
    substance: Mapped[str] = mapped_column(String(200))
    reaction: Mapped[str] = mapped_column(Text, default="")
    severity: Mapped[str] = mapped_column(String(40), default="")
    verification: Mapped[str] = mapped_column(String(20), default="pending")
    reported_by: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Medication(Base):
    __tablename__ = "medication"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_id)
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patient.id"))
    name: Mapped[str] = mapped_column(String(200))
    strength: Mapped[str] = mapped_column(String(80), default="")
    instruction: Mapped[str] = mapped_column(Text, default="")
    scheduled_times: Mapped[list] = mapped_column(JSON, default=list)  # ["08:00","20:00"]
    verification: Mapped[str] = mapped_column(String(20), default="pending")
    verified_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("user.id"), nullable=True)
    source: Mapped[str] = mapped_column(String(80), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Routine(Base):
    __tablename__ = "routine"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_id)
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patient.id"))
    kind: Mapped[str] = mapped_column(String(20))  # wake|meal|walk|bath|sleep|other
    preferred_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")


class Assignment(Base):
    __tablename__ = "assignment"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_id)
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patient.id"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user.id"))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class TodoTemplate(Base):
    __tablename__ = "todo_template"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_id)
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patient.id"))
    medication_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("medication.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(20))
    source: Mapped[str] = mapped_column(String(20))  # medication|routine|care_plan|agent_proposal
    default_time: Mapped[time] = mapped_column(Time)
    recurrence: Mapped[str] = mapped_column(String(40), default="daily")
    note: Mapped[str] = mapped_column(Text, default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Todo(Base):
    __tablename__ = "todo"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_id)
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patient.id"))
    caretaker_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("user.id"), nullable=True)
    template_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("todo_template.id"), nullable=True)
    due_date: Mapped[date] = mapped_column(Date)
    due_time: Mapped[time] = mapped_column(Time)
    title: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="todo")
    priority_score: Mapped[int] = mapped_column(Integer, default=0)
    priority_reason: Mapped[str] = mapped_column(Text, default="")
    memory_chip: Mapped[str] = mapped_column(String(80), default="")
    status_note: Mapped[str] = mapped_column(Text, default="")
    checkin_sent: Mapped[bool] = mapped_column(Boolean, default=False)


class TodoEvent(Base):
    __tablename__ = "todo_event"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_id)
    todo_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("todo.id"))
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("user.id"), nullable=True)
    from_status: Mapped[str] = mapped_column(String(20))
    to_status: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str] = mapped_column(Text, default="")
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class CareLog(Base):
    __tablename__ = "care_log"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_id)
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patient.id"))
    caretaker_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user.id"))
    category: Mapped[str] = mapped_column(String(20))
    structured: Mapped[dict] = mapped_column(JSON, default=dict)
    narrative: Mapped[str] = mapped_column(Text, default="")
    severity: Mapped[str] = mapped_column(String(10), default="normal")
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    chat_message_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)


class MemoryLink(Base):
    __tablename__ = "memory_link"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_id)
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patient.id"))
    source_type: Mapped[str] = mapped_column(String(20))
    source_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    hindsight_document_id: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(10), default="pending")  # retained|failed|pending
    payload: Mapped[dict] = mapped_column(JSON, default=dict)  # for retry
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class LocalMemory(Base):
    """Fact store used by the local memory backend (no Hindsight key)."""

    __tablename__ = "local_memory"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_id)
    bank_id: Mapped[str] = mapped_column(String(200), index=True)
    text: Mapped[str] = mapped_column(Text)
    context: Mapped[str] = mapped_column(String(60), default="")
    document_id: Mapped[str] = mapped_column(String(120), default="")
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    meta: Mapped[dict] = mapped_column(JSON, default=dict)


class Alert(Base):
    __tablename__ = "alert"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_id)
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patient.id"))
    kind: Mapped[str] = mapped_column(String(20))  # trend|urgent_log|missed_med|verification
    signal: Mapped[str] = mapped_column(String(20), default="")
    summary: Mapped[str] = mapped_column(Text)
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(20), default="open")
    acknowledged_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("user.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Suggestion(Base):
    __tablename__ = "suggestion"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_id)
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patient.id"))
    kind: Mapped[str] = mapped_column(String(20))  # what_worked|reschedule
    title: Mapped[str] = mapped_column(String(300), default="")
    text: Mapped[str] = mapped_column(Text)
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="proposed")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ChatMessage(Base):
    __tablename__ = "chat_message"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_id)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user.id"))
    patient_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("patient.id"), nullable=True)
    role: Mapped[str] = mapped_column(String(10))
    content: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class AuditEvent(Base):
    __tablename__ = "audit_event"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_id)
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    action: Mapped[str] = mapped_column(String(60))
    patient_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


__all__ = [n for n in dir() if n[0].isupper() and n not in ("TS", "Mapped")]
relationship  # noqa: B018
