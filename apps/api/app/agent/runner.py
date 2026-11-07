"""One chat turn → stream of SSE events: token, card, quick_replies, memory_used, board_changed, done."""
import logging
import re
import uuid
from collections.abc import AsyncIterator

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import guard
from app.agent import actions, rules
from app.agent.context import Ctx
from app.agent.llm import LLMUnavailable, drive_llm
from app.agent.tools import RaiseEscalationArgs, raise_escalation
from app.auth.deps import assigned_patient_ids
from app.core.config import get_settings
from app.memory.service import MemoryService
from app.models import ChatMessage, Patient, User
from app.services.facts import evidence_line

log = logging.getLogger(__name__)


def _add(session, persist, obj):
    if persist:
        session.add(obj)


async def load_ctx(session: AsyncSession, user: User, memory: MemoryService, patient_id: str | None) -> Ctx:
    ids = await assigned_patient_ids(session, user)
    pats = {p.id: p for p in await session.scalars(select(Patient).where(Patient.id.in_(ids)))}
    ctx = Ctx(session=session, user=user, memory=memory, patients=pats)
    if patient_id:
        try:
            ctx.active = pats.get(uuid.UUID(patient_id))
        except ValueError:
            ctx.active = None
    return ctx


def _mem_payload(ctx: Ctx) -> list[dict]:
    out = []
    for i in ctx.used.values():
        e = evidence_line(i)
        out.append({"id": i.id, "date": e["date"], "caretaker": i.caretaker_name, "text": i.text, "type": i.type,
                    "proof_count": i.proof_count})
    return out


async def run_turn(session: AsyncSession, user: User, memory: MemoryService, *, message: str | None = None,
                   action: str | None = None, payload: dict | None = None, patient_id: str | None = None,
                   persist: bool = True) -> AsyncIterator[dict]:
    ctx = await load_ctx(session, user, memory, patient_id)
    payload = payload or {}
    text, label = "", message or ""
    try:
        if action:
            if action == "select_patient":
                ctx.active = ctx.patient(payload["patient_id"])
                message, action = payload["message"], None
            else:
                label = _label(action, payload)
                _add(session, persist, ChatMessage(user_id=user.id, patient_id=ctx.active.id if ctx.active else None, role="user", content=label))
                text = await actions.run_action(ctx, action, payload)
        if not action:
            _add(session, persist, ChatMessage(user_id=user.id, patient_id=ctx.active.id if ctx.active else None, role="user", content=message or ""))
            v = guard.check_input(message or "")
            if v.blocked:
                text = v.reply
            else:
                if v.urgent:
                    p = rules.resolve_patient(ctx, message or "")
                    if p:
                        ctx.active = p
                        await raise_escalation(ctx, RaiseEscalationArgs(patient_id=p.id, summary=f"Urgent sign reported: {message}"))
                text = await _drive(ctx, message or "", session, user)
                if v.urgent:
                    text = guard.EMERGENCY + "<br>" + text
            rules.draft_card(ctx)
    except PermissionError as e:
        text = f"I can't do that: {e}."
    except LookupError:
        log.info("patient unresolved → asking", exc_info=True)
        text = rules.ask_patient(ctx, message or "")
    except Exception:  # noqa: BLE001
        log.exception("chat turn failed")
        text = "Sorry, something went wrong on my side. Nothing was changed."
    if ctx.notes:
        text += "<br>" + " ".join(ctx.notes)
    text, cards, violations = guard.check_output(text, ctx.cards)
    if violations:
        log.warning("guard violations: %s", violations)
        ctx.quick = [] if "dose" in violations or "diagnosis" in violations else ctx.quick
    _add(session, persist, ChatMessage(user_id=user.id, patient_id=ctx.active.id if ctx.active else None, role="assistant", content=text,
                            payload={"cards": cards, "quick": ctx.quick, "memory": _mem_payload(ctx)}))
    await session.commit()
    for chunk in re.findall(r"\S+\s*|\s+", text):
        yield {"event": "token", "data": {"text": chunk}}
    for c in cards:
        yield {"event": "card", "data": c}
    if ctx.quick:
        yield {"event": "quick_replies", "data": {"replies": ctx.quick}}
    if ctx.used and memory.enabled:
        yield {"event": "memory_used", "data": {"items": _mem_payload(ctx)}}
    if ctx.board_changed:
        yield {"event": "board_changed", "data": {}}
    yield {"event": "done", "data": {}}


def _label(action: str, p: dict) -> str:
    return {"checkin_status": {"done": "Completed", "not_done": "Not done", "skipped": "Skipped"}.get(p.get("status", ""), action),
            "todo_reason": p.get("detail") or p.get("reason", ""), "accept_suggestion": "Yes", "dismiss_suggestion": "No thanks",
            "save_logs": "Save", "edit_logs": "Edit", "checkin_start": "Check in on todos"}.get(action, action) or "Skip detail"


async def _drive(ctx: Ctx, text: str, session: AsyncSession, user: User) -> str:
    if not ctx.active:
        p = rules.resolve_patient(ctx, text)
        if p and len([x for x in ctx.patients.values() if x.full_name.split()[0].lower() in text.lower()]) == 1:
            ctx.active = p
    if get_settings().groq_api_key and not rules.is_structured(text):
        hist = []
        rows = list(await session.scalars(select(ChatMessage).where(ChatMessage.user_id == user.id).order_by(ChatMessage.created_at.desc()).limit(8)))
        for r in reversed(rows[1:]):
            hist.append({"role": r.role, "content": re.sub(r"<[^>]+>", "", r.content)})
        try:
            ctx.drafts.clear()
            return await drive_llm(ctx, text, hist)
        except LLMUnavailable:
            log.warning("LLM unavailable → rule driver")
            ctx.cards.clear(); ctx.quick.clear(); ctx.drafts.clear()  # noqa: E702
    return await rules.drive(ctx, text)
