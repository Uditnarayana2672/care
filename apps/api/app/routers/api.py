import json
import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.actions import checkin_prompt, due_checkins
from app.agent.context import Ctx
from app.agent.runner import load_ctx, run_turn
from app.auth.deps import (
    COOKIE,
    assigned_patient_ids,
    audit,
    check_assignment,
    get_current_user,
    make_token,
    require_assignment,
    require_role,
)
from app.core import events
from app.core.config import get_settings
from app.core.db import get_session
from app.core.time import aware, fmt_dt, local_now, today
from app.learning.failures import decide
from app.memory.service import MemoryService, get_memory
from app.models import (
    Alert,
    Allergy,
    Assignment,
    CareLog,
    ChatMessage,
    Condition,
    Medication,
    MemoryLink,
    Organization,
    Patient,
    PatientContact,
    Routine,
    Suggestion,
    Todo,
    TodoEvent,
    User,
)
from app.orchestrator.board import build_board, initials
from app.routers.deps import memory_dep, optional_user
from app.schemas import ChatIn, DemoLogin, EnrollmentIn, MemoryToggleIn, StatusIn, VerifyIn
from app.services import enroll as enroll_svc
from app.services import todos as todo_svc
from app.trends.watch import acknowledge

router = APIRouter()


# ------------------------------------------------------------------ auth
@router.get("/auth/demo-users")
async def demo_users(session: AsyncSession = Depends(get_session)):
    rows = await session.scalars(select(User).order_by(User.role, User.full_name))
    return [{"id": str(u.id), "email": u.email, "name": u.full_name, "role": u.role} for u in rows]


@router.post("/auth/demo-login")
async def demo_login(body: DemoLogin, response: Response, session: AsyncSession = Depends(get_session)):
    u = await session.scalar(select(User).where(User.email == body.email))
    if not u:
        raise HTTPException(404, "Unknown demo user")
    tok = make_token(u)
    response.set_cookie(COOKIE, tok, httponly=True, samesite="lax", max_age=7 * 86400)
    return {"token": tok, "user": {"id": str(u.id), "name": u.full_name, "role": u.role, "email": u.email}}


@router.post("/auth/logout")
async def logout(response: Response):
    response.delete_cookie(COOKIE)
    return {"ok": True}


@router.get("/auth/me")
async def me(user: User = Depends(get_current_user)):
    return {"id": str(user.id), "name": user.full_name, "role": user.role, "email": user.email}


# ------------------------------------------------------------------ enrollment
@router.post("/enrollments", status_code=201)
async def create_enrollment(body: EnrollmentIn, user: User | None = Depends(optional_user),
                            session: AsyncSession = Depends(get_session), memory: MemoryService = Depends(memory_dep)):
    p = await enroll_svc.enroll(session, memory, body, user)
    return {"patient_id": str(p.id), "code": p.code, "bank_ready": True}


# ------------------------------------------------------------------ patients
def _pt(p: Patient) -> dict:
    return {"id": str(p.id), "name": p.full_name, "initials": initials(p.full_name), "color": p.color, "age": p.age,
            "gender": p.gender, "language": p.preferred_language, "mobility": p.mobility_level, "diet": p.diet_type,
            "code": p.code}


@router.get("/patients")
async def list_patients(user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    ids = await assigned_patient_ids(session, user)
    rows = await session.scalars(select(Patient).where(Patient.id.in_(ids)).order_by(Patient.full_name))
    return [_pt(p) for p in rows]


@router.get("/patients/{patient_id}")
async def get_patient(p: Patient = Depends(require_assignment), user: User = Depends(get_current_user),
                      session: AsyncSession = Depends(get_session)):
    await audit(session, user, "read_profile", p.id)
    meds = await session.scalars(select(Medication).where(Medication.patient_id == p.id))
    alg = await session.scalars(select(Allergy).where(Allergy.patient_id == p.id))
    rt = await session.scalars(select(Routine).where(Routine.patient_id == p.id))
    cond = await session.scalars(select(Condition).where(Condition.patient_id == p.id))
    contacts = await session.scalars(select(PatientContact).where(PatientContact.patient_id == p.id))
    await session.commit()
    return {**_pt(p), "hearing_vision": p.hearing_vision, "phone": p.phone, "address": p.address,
            "conditions": [c.name for c in cond], "contacts": [{"name": c.name, "relation": c.relation, "phone": c.phone} for c in contacts],
            "medications": [{"id": str(m.id), "name": m.name, "strength": m.strength, "times": m.scheduled_times, "verification": m.verification} for m in meds],
            "allergies": [{"id": str(a.id), "substance": a.substance, "reaction": a.reaction, "verification": a.verification} for a in alg],
            "routines": [{"kind": r.kind, "time": r.preferred_time.strftime("%H:%M") if r.preferred_time else None, "notes": r.notes} for r in rt]}


@router.get("/patients/{patient_id}/today")
async def patient_today(p: Patient = Depends(require_assignment), user: User = Depends(get_current_user),
                        session: AsyncSession = Depends(get_session), memory: MemoryService = Depends(memory_dep)):
    board = await build_board(session, memory, user)
    return [c for col in board["columns"] for c in col["cards"] if c["patient_id"] == str(p.id)]


@router.get("/patients/{patient_id}/timeline")
async def timeline(p: Patient = Depends(require_assignment), session: AsyncSession = Depends(get_session)):
    names = {u.id: u.full_name.split()[0] for u in await session.scalars(select(User))}
    logs = await session.scalars(select(CareLog).where(CareLog.patient_id == p.id).order_by(CareLog.observed_at.desc()).limit(60))
    evs = await session.execute(select(TodoEvent, Todo).join(Todo, TodoEvent.todo_id == Todo.id)
                                .where(Todo.patient_id == p.id, TodoEvent.to_status.in_(["done", "not_done", "skipped"]))
                                .order_by(TodoEvent.at.desc()).limit(60))
    out = [{"at": aware(l.observed_at).isoformat(), "kind": "log", "category": l.category, "severity": l.severity,
            "text": l.narrative or l.category, "by": names.get(l.caretaker_id, ""), "id": str(l.id)} for l in logs]
    out += [{"at": aware(e.at).isoformat(), "kind": "todo", "category": t.category, "severity": "normal",
             "text": f"{t.title} — {e.to_status.replace('_', ' ')}" + (f" ({e.reason})" if e.reason else ""),
             "by": names.get(e.actor_id, ""), "id": str(e.id)} for e, t in evs]
    return sorted(out, key=lambda x: x["at"], reverse=True)[:80]


@router.get("/patients/{patient_id}/memory")
async def patient_memory(p: Patient = Depends(require_assignment), user: User = Depends(get_current_user),
                         session: AsyncSession = Depends(get_session), memory: MemoryService = Depends(memory_dep),
                         category: str | None = None):
    await audit(session, user, "read_memory", p.id)
    await session.commit()
    obs = await memory.observations(p, "")
    recent = await memory.list_recent(p, 80)
    recent = sorted([r for r in recent if r.occurred_at], key=lambda r: aware(r.occurred_at), reverse=True)
    if category:
        recent = [r for r in recent if r.context == category or r.category == category]
    def ev(i):
        return {"id": i.id, "date": aware(i.occurred_at).isoformat() if i.occurred_at else None, "caretaker": i.caretaker_name,
                "text": i.brief or i.text, "full": i.text, "context": i.context, "source_type": i.source_type, "source_id": i.source_id}
    return {"enabled": memory.enabled,
            "observations": [{"id": o.id, "text": o.text, "kind": o.pattern_kind, "proof_count": o.proof_count,
                              "evidence": [ev(e) for e in o.evidence]} for o in obs],
            "recent": [ev(r) for r in recent[:40]]}


@router.get("/patients/{patient_id}/trends")
async def patient_trends(p: Patient = Depends(require_assignment), session: AsyncSession = Depends(get_session)):
    async def series(cat: str, key: str, n: int = 14):
        rows = list(await session.scalars(select(CareLog).where(CareLog.patient_id == p.id, CareLog.category == cat)
                                          .order_by(CareLog.observed_at.desc()).limit(n)))
        return [{"date": aware(r.observed_at).strftime("%Y-%m-%d"), "value": r.structured.get(key)} for r in reversed(rows)]
    return {"sleep": await series("sleep", "hours"), "diet": await series("diet", "portion")}


# ------------------------------------------------------------------ board, todos
@router.get("/me/board")
async def board(date_: date | None = None, user: User = Depends(require_role("caretaker", "coordinator")),
                session: AsyncSession = Depends(get_session), memory: MemoryService = Depends(memory_dep)):
    return await build_board(session, memory, user, date_)


@router.patch("/todos/{todo_id}")
async def patch_todo(todo_id: uuid.UUID, body: StatusIn, user: User = Depends(get_current_user),
                     session: AsyncSession = Depends(get_session), memory: MemoryService = Depends(memory_dep)):
    todo = await todo_svc.get_todo_for(session, todo_id)
    await check_assignment(session, user, todo.patient_id)
    res = await todo_svc.set_status(session, memory, user, todo, body.status, body.reason)
    s = res.suggestion
    return {"id": str(todo.id), "status": todo.status,
            "suggestion": {"id": str(s.id), "title": s.title, "text": s.text, "evidence": s.evidence} if s else None,
            "coordinator_hint": res.coordinator_hint}


@router.get("/me/checkins")
async def checkins(user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session),
                   memory: MemoryService = Depends(memory_dep)):
    ctx = await load_ctx(session, user, memory, None)
    rows = await due_checkins(ctx)
    return [{"todo_id": str(t.id), "prompt": checkin_prompt(ctx, t)} for t in rows]


@router.get("/me/events")
async def my_events(request: Request, user: User = Depends(get_current_user)):
    async def gen():
        async for ev in events.subscribe(f"user:{user.id}"):
            if await request.is_disconnected():
                break
            yield f"data: {json.dumps(ev)}\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


# ------------------------------------------------------------------ chat
@router.post("/chat")
async def chat(body: ChatIn, user: User = Depends(require_role("caretaker", "coordinator")),
               session: AsyncSession = Depends(get_session), memory: MemoryService = Depends(memory_dep)):
    if body.patient_id:
        await check_assignment(session, user, body.patient_id)

    async def gen():
        async for ev in run_turn(session, user, memory, message=body.message, action=body.action, payload=body.payload,
                                 patient_id=str(body.patient_id) if body.patient_id else None):
            yield f"event: {ev['event']}\ndata: {json.dumps(ev['data'], default=str)}\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/chat/history")
async def chat_history(patient_id: uuid.UUID | None = None, user: User = Depends(get_current_user),
                       session: AsyncSession = Depends(get_session)):
    if patient_id:
        await check_assignment(session, user, patient_id)
    q = select(ChatMessage).where(ChatMessage.user_id == user.id)
    if patient_id:
        q = q.where(ChatMessage.patient_id == patient_id)
    rows = await session.scalars(q.order_by(ChatMessage.created_at.desc()).limit(50))
    return [{"id": str(m.id), "role": m.role, "content": m.content, "payload": m.payload, "at": aware(m.created_at).isoformat()}
            for m in reversed(list(rows))]


# ------------------------------------------------------------------ suggestions, alerts
async def _sug(session, user, sid) -> Suggestion:
    s = await session.get(Suggestion, sid)
    if not s:
        raise HTTPException(404, "Suggestion not found")
    await check_assignment(session, user, s.patient_id)
    return s


@router.post("/suggestions/{sid}/accept")
async def accept(sid: uuid.UUID, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session),
                 memory: MemoryService = Depends(memory_dep)):
    s = await decide(session, memory, user, await _sug(session, user, sid), True)
    return {"id": str(s.id), "status": s.status}


@router.post("/suggestions/{sid}/dismiss")
async def dismiss(sid: uuid.UUID, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session),
                  memory: MemoryService = Depends(memory_dep)):
    s = await decide(session, memory, user, await _sug(session, user, sid), False)
    return {"id": str(s.id), "status": s.status}


@router.get("/alerts")
async def alerts(user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    ids = await assigned_patient_ids(session, user)
    pats = {p.id: p for p in await session.scalars(select(Patient).where(Patient.id.in_(ids)))}
    rows = await session.scalars(select(Alert).where(Alert.patient_id.in_(ids)).order_by(Alert.created_at.desc()))
    return [{"id": str(a.id), "patient_id": str(a.patient_id), "patient_name": pats[a.patient_id].full_name, "kind": a.kind,
             "signal": a.signal, "summary": a.summary, "evidence": a.evidence, "status": a.status,
             "created_at": aware(a.created_at).isoformat()} for a in rows]


async def _alert(session, user, aid) -> Alert:
    a = await session.get(Alert, aid)
    if not a:
        raise HTTPException(404, "Alert not found")
    await check_assignment(session, user, a.patient_id)
    return a


@router.post("/alerts/{aid}/ack")
async def ack(aid: uuid.UUID, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session),
              memory: MemoryService = Depends(memory_dep)):
    a = await acknowledge(session, memory, user, await _alert(session, user, aid))
    return {"id": str(a.id), "status": a.status}


@router.post("/alerts/{aid}/resolve")
async def resolve(aid: uuid.UUID, user: User = Depends(require_role("coordinator")), session: AsyncSession = Depends(get_session)):
    a = await _alert(session, user, aid)
    a.status = "resolved"
    await audit(session, user, "resolve_alert", a.patient_id, alert=str(a.id))
    await session.commit()
    return {"id": str(a.id), "status": a.status}


# ------------------------------------------------------------------ coordinator
@router.get("/coordinator/verifications")
async def verifications(user: User = Depends(require_role("coordinator")), session: AsyncSession = Depends(get_session)):
    ids = await assigned_patient_ids(session, user)
    pats = {p.id: p for p in await session.scalars(select(Patient).where(Patient.id.in_(ids)))}
    meds = await session.scalars(select(Medication).where(Medication.patient_id.in_(ids), Medication.verification == "pending"))
    alg = await session.scalars(select(Allergy).where(Allergy.patient_id.in_(ids), Allergy.verification == "pending"))
    out = [{"id": str(m.id), "kind": "medication", "patient": pats[m.patient_id].full_name,
            "item": f"{m.name} {m.strength} · {', '.join(m.scheduled_times)}".replace("  ", " "), "source": m.source or "Self-enrollment"}
           for m in meds]
    out += [{"id": str(a.id), "kind": "allergy", "patient": pats[a.patient_id].full_name,
             "item": f"{a.substance}" + (f" — {a.reaction}" if a.reaction else ""),
             "source": f"{a.reported_by} · chat log" if a.reported_by and a.reported_by != "enrollment" else "Self-enrollment"} for a in alg]
    escal = await session.scalars(select(Alert).where(Alert.patient_id.in_(ids), Alert.status.in_(["open", "acknowledged"]),
                                                      Alert.kind.in_(["trend", "urgent_log", "escalation", "missed_med"])))
    return {"queue": out, "escalations": [{"id": str(a.id), "patient": pats[a.patient_id].full_name, "summary": a.summary,
                                           "status": a.status, "evidence": a.evidence} for a in escal]}


@router.post("/coordinator/verifications/{item_id}")
async def verify(item_id: uuid.UUID, body: VerifyIn, user: User = Depends(require_role("coordinator")),
                 session: AsyncSession = Depends(get_session), memory: MemoryService = Depends(memory_dep)):
    model = Medication if body.kind == "medication" else Allergy
    item = await session.get(model, item_id)
    if not item:
        raise HTTPException(404, "Item not found")
    p = await check_assignment(session, user, item.patient_id)
    item.verification = body.decision
    if body.kind == "medication" and body.decision == "verified":
        item.verified_by = user.id
    await audit(session, user, f"verify_{body.kind}", p.id, decision=body.decision)
    from app.core.time import now
    name = item.name if body.kind == "medication" else item.substance
    await memory.retain_fact(p, text=f"On {fmt_dt(now())}, coordinator {user.full_name.split()[0]} {body.decision} {body.kind} '{name}'.",
                             occurred_at=now(), context="verification", source_type="verification", source_id=item.id,
                             metadata={"category": "verification", "caretaker_name": user.full_name.split()[0]}, session=session)
    if body.kind == "medication" and body.decision == "verified":
        from app.orchestrator.generate import generate_for_patient
        await generate_for_patient(session, p, today())
    await session.commit()
    return {"id": str(item.id), "verification": item.verification}


@router.post("/coordinator/assignments")
async def assign(patient_id: uuid.UUID, user_id: uuid.UUID, user: User = Depends(require_role("coordinator")),
                 session: AsyncSession = Depends(get_session)):
    await check_assignment(session, user, patient_id)
    session.add(Assignment(patient_id=patient_id, user_id=user_id))
    await session.commit()
    return {"ok": True}


@router.get("/memory/links")
async def memory_links(patient_id: uuid.UUID, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    await check_assignment(session, user, patient_id)
    rows = await session.scalars(select(MemoryLink).where(MemoryLink.patient_id == patient_id).order_by(MemoryLink.created_at.desc()).limit(100))
    return [{"doc": m.hindsight_document_id, "status": m.status, "attempts": m.attempts} for m in rows]


# ------------------------------------------------------------------ demo
@router.post("/demo/memory-toggle")
async def memory_toggle(body: MemoryToggleIn, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    mem = get_memory()
    if body.enabled is not None:
        mem.enabled = body.enabled
    if not body.question:
        return {"enabled": mem.enabled}
    if body.patient_id:
        await check_assignment(session, user, body.patient_id)
    out = {}
    for label, on in (("off", False), ("on", True)):
        svc = MemoryService(backend=mem.backend, enabled=on)
        text, cards = "", []
        async for ev in run_turn(session, user, svc, message=body.question, patient_id=str(body.patient_id) if body.patient_id else None,
                                 persist=False):
            if ev["event"] == "token":
                text += ev["data"]["text"]
            elif ev["event"] == "card":
                cards.append(ev["data"])
        out[label] = {"text": text, "cards": cards}
    return {"enabled": mem.enabled, **out}


@router.get("/health")
async def health():
    return {"status": "ok", "memory_backend": get_memory().backend.name, "llm": "groq" if get_settings().groq_api_key else "rules",
            "now": local_now().isoformat()}


__all__ = ["router", "Organization", "Ctx"]
