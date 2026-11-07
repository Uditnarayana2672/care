"""Tool registry (architecture §7.2). There is deliberately NO tool that creates or edits medications."""
import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import select

from app.agent.context import Ctx
from app.core.time import aware, local_now, today
from app.learning.what_worked import what_worked as ww
from app.models import Alert, Allergy, Medication, Patient, Routine, Suggestion, Todo, TodoTemplate
from app.services import logs as log_svc
from app.services import todos as todo_svc
from app.services.facts import evidence_line

Category = Literal["medication", "sleep", "diet", "mood", "mobility", "progress", "allergy", "observation"]


class ListTodosArgs(BaseModel):
    patient_id: uuid.UUID | None = None
    status: Literal["todo", "in_progress", "done", "not_done", "skipped"] | None = None


class UpdateTodoStatusArgs(BaseModel):
    todo_id: uuid.UUID
    status: Literal["todo", "in_progress", "done", "not_done", "skipped"]
    reason: str | None = None


class LogCareArgs(BaseModel):
    patient_id: uuid.UUID | None = None
    category: Category
    structured: dict[str, Any] = Field(default_factory=dict)
    narrative: str = ""
    severity: Literal["normal", "watch", "urgent"] = "normal"
    observed_at: datetime | None = None


class ReportAllergyArgs(BaseModel):
    patient_id: uuid.UUID | None = None
    substance: str = Field(min_length=2)
    reaction: str = ""


class RecallArgs(BaseModel):
    patient_id: uuid.UUID | None = None
    query: str
    types: list[Literal["world", "experience", "observation"]] | None = None


class AskMemoryArgs(BaseModel):
    patient_id: uuid.UUID | None = None
    question: str


class WhatWorkedArgs(BaseModel):
    patient_id: uuid.UUID | None = None
    situation: str


class ProposeRescheduleArgs(BaseModel):
    todo_template_id: uuid.UUID
    new_time: str = Field(pattern=r"^\d{2}:\d{2}$")
    evidence_ids: list[str] = Field(min_length=1)


class RaiseEscalationArgs(BaseModel):
    patient_id: uuid.UUID | None = None
    summary: str
    evidence_ids: list[str] = Field(default_factory=list)


class ProfileArgs(BaseModel):
    patient_id: uuid.UUID | None = None


async def list_todos(ctx: Ctx, a: ListTodosArgs) -> dict:
    ids = [ctx.patient(a.patient_id).id] if a.patient_id or ctx.active else list(ctx.patients)
    q = select(Todo).where(Todo.patient_id.in_(ids), Todo.due_date == today()).order_by(Todo.due_time)
    if a.status:
        q = q.where(Todo.status == a.status)
    rows = list(await ctx.session.scalars(q))
    return {"todos": [{"id": str(t.id), "patient": ctx.patients[t.patient_id].full_name, "title": t.title,
                       "time": t.due_time.strftime("%H:%M"), "status": t.status} for t in rows]}


async def update_todo_status(ctx: Ctx, a: UpdateTodoStatusArgs) -> dict:
    todo = await ctx.session.get(Todo, a.todo_id)
    if not todo or todo.patient_id not in ctx.patients:
        return {"error": "Todo not found among your patients"}
    res = await todo_svc.set_status(ctx.session, ctx.memory, ctx.user, todo, a.status, a.reason or "")
    ctx.board_changed = True
    p = ctx.patients[todo.patient_id]
    if res.suggestion:
        add_suggestion_card(ctx, res.suggestion, p)
    if res.coordinator_hint:
        ctx.notes.append(res.coordinator_hint)
    return {"ok": True, "status": a.status, "suggestion": bool(res.suggestion), "coordinator_hint": res.coordinator_hint}


async def log_care(ctx: Ctx, a: LogCareArgs) -> dict:
    p = ctx.patient(a.patient_id)
    ctx.drafts.append({"patient_id": str(p.id), "category": a.category, "structured": a.structured,
                       "narrative": a.narrative, "severity": a.severity,
                       "observed_at": (a.observed_at or local_now()).isoformat()})
    return {"queued_for_confirmation": True, "patient": p.full_name}


async def report_allergy(ctx: Ctx, a: ReportAllergyArgs) -> dict:
    p = ctx.patient(a.patient_id)
    r = await log_svc.save_log(ctx.session, ctx.memory, ctx.user, p, category="allergy",
                               structured={"substance": a.substance, "reaction": a.reaction},
                               narrative=f"{a.reaction or 'Reaction'} after {a.substance}", severity="watch")
    return {"ok": True, "verification": "pending", "log_id": str(r.log.id)}


async def recall_memory(ctx: Ctx, a: RecallArgs) -> dict:
    p = ctx.patient(a.patient_id)
    items = await ctx.memory.recall(p, a.query, types=list(a.types) if a.types else None)
    ctx.use(items)
    return {"memories": [evidence_line(i) | {"type": i.type, "proof_count": i.proof_count} for i in items]}


async def ask_memory(ctx: Ctx, a: AskMemoryArgs) -> dict:
    p = ctx.patient(a.patient_id)
    ans = await ctx.memory.reflect(p, a.question)
    ctx.use(ans.items)
    if not ans.items:
        return {"answer": "", "note": "Not enough information in memory. Suggest asking the previous caretaker or coordinator."}
    return {"answer": ans.text, "citations": [evidence_line(i) for i in ans.items]}


def add_suggestion_card(ctx: Ctx, s: Suggestion, p: Patient) -> None:
    if not s.evidence:
        return  # guard rule: uncited suggestions are never shown
    ctx.card({"type": "suggestion", "kind": s.kind, "id": str(s.id), "title": s.title, "text": s.text, "evidence": s.evidence,
              "note": "Observed pattern — not a clinical instruction. You decide."})
    if s.kind == "reschedule":
        t = s.params.get("new_time", "")
        ctx.qr(f"Yes, move to {datetime.strptime(t, '%H:%M').strftime('%-I:%M %p')}" if t else "Yes, move it", "accept_suggestion", id=str(s.id))
        ctx.qr("Keep as is", "dismiss_suggestion", id=str(s.id))
    else:
        ctx.qr("Try it", "accept_suggestion", id=str(s.id))
        ctx.qr("Not now", "dismiss_suggestion", id=str(s.id))
    ctx.use([])  # no-op; evidence rendered on the card


async def what_worked(ctx: Ctx, a: WhatWorkedArgs) -> dict:
    p = ctx.patient(a.patient_id)
    s = await ww(ctx.session, ctx.memory, p, a.situation)
    if not s:
        return {"suggestion": None, "note": "No pattern with enough evidence (needs at least 2 supporting facts in 30 days)."}
    add_suggestion_card(ctx, s, p)
    return {"suggestion": s.title, "evidence_count": len(s.evidence)}


async def propose_reschedule(ctx: Ctx, a: ProposeRescheduleArgs) -> dict:
    tpl = await ctx.session.get(TodoTemplate, a.todo_template_id)
    if not tpl or tpl.patient_id not in ctx.patients:
        return {"error": "Template not found among your patients"}
    if tpl.category == "medication":
        return {"error": "Medication timing cannot be changed here. Suggest discussing with the coordinator or doctor."}
    ev = [evidence_line(ctx.seen[i]) for i in a.evidence_ids if i in ctx.seen]
    if not ev:
        return {"error": "No valid evidence ids; recall memory first and cite its ids."}
    p = ctx.patients[tpl.patient_id]
    s = Suggestion(patient_id=p.id, kind="reschedule", title=f"Move {ctx.first(p)}'s {tpl.title.lower()} to {a.new_time}?",
                   text=f"Proposed new time {a.new_time} for {tpl.title}.", evidence=ev,
                   params={"template_id": str(tpl.id), "new_time": a.new_time})
    ctx.session.add(s)
    await ctx.session.commit()
    add_suggestion_card(ctx, s, p)
    return {"suggestion_id": str(s.id)}


async def raise_escalation(ctx: Ctx, a: RaiseEscalationArgs) -> dict:
    p = ctx.patient(a.patient_id)
    ev = [evidence_line(ctx.seen[i]) for i in a.evidence_ids if i in ctx.seen]
    al = Alert(patient_id=p.id, kind="escalation", signal="urgent", summary=a.summary, evidence=ev)
    ctx.session.add(al)
    await ctx.session.commit()
    ctx.escalated = True
    return {"alert_id": str(al.id)}


async def get_patient_profile(ctx: Ctx, a: ProfileArgs) -> dict:
    p = ctx.patient(a.patient_id)
    meds = list(await ctx.session.scalars(select(Medication).where(Medication.patient_id == p.id)))
    alg = list(await ctx.session.scalars(select(Allergy).where(Allergy.patient_id == p.id)))
    rt = list(await ctx.session.scalars(select(Routine).where(Routine.patient_id == p.id)))
    return {"id": str(p.id), "name": p.full_name, "age": p.age, "language": p.preferred_language, "mobility": p.mobility_level,
            "diet": p.diet_type,
            "medications": [{"id": str(m.id), "name": m.name, "strength": m.strength, "times": m.scheduled_times,
                             "verification": m.verification} for m in meds],
            "allergies": [{"substance": x.substance, "verification": x.verification} for x in alg],
            "routines": [{"kind": r.kind, "time": r.preferred_time.strftime("%H:%M") if r.preferred_time else None} for r in rt]}


TOOLS: dict[str, tuple[type[BaseModel], Any, str]] = {
    "list_todos": (ListTodosArgs, list_todos, "List today's todos for the caretaker."),
    "update_todo_status": (UpdateTodoStatusArgs, update_todo_status, "Change a todo's status. reason required for not_done/skipped."),
    "log_care": (LogCareArgs, log_care, "Record an observation as a care log (the caretaker confirms before it is saved). One call per entry."),
    "report_allergy": (ReportAllergyArgs, report_allergy, "Report a possible allergy; stored as pending coordinator verification."),
    "recall_memory": (RecallArgs, recall_memory, "Search the patient's memory. Returns evidence with ids."),
    "ask_memory": (AskMemoryArgs, ask_memory, "Ask the patient's memory a question (reflect). Returns answer and citations."),
    "what_worked": (WhatWorkedArgs, what_worked, "Find observed patterns that helped in a similar situation."),
    "propose_reschedule": (ProposeRescheduleArgs, propose_reschedule, "Propose moving a non-medication task to a new time, citing memory evidence ids."),
    "raise_escalation": (RaiseEscalationArgs, raise_escalation, "Escalate to the coordinator."),
    "get_patient_profile": (ProfileArgs, get_patient_profile, "Authoritative profile, medications, allergies, routines."),
}


def openai_tools() -> list[dict]:
    out = []
    for name, (model, _fn, desc) in TOOLS.items():
        schema = model.model_json_schema()
        schema.pop("title", None)
        out.append({"type": "function", "function": {"name": name, "description": desc, "parameters": schema}})
    return out


__all__ = ["TOOLS", "openai_tools", "aware"]
