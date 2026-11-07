"""Button actions (quick replies / check-ins). Same service functions as tools and Kanban drag."""
import uuid
from datetime import datetime

from sqlalchemy import select

from app.agent import tools as T
from app.agent.context import Ctx
from app.core.time import at_local, aware, now, today
from app.learning.failures import decide
from app.models import Suggestion, Todo
from app.services import logs as log_svc
from app.services import todos as todo_svc

DETAIL = {"Refused": ["Feels cold", "Doesn't want to", "Skip detail"], "Unwell": ["Skip detail"], "Other": ["Skip detail"],
          "Asleep": [], "No time": []}


async def due_checkins(ctx: Ctx, any_open: bool = False) -> list[Todo]:
    ids = list(ctx.patients)
    rows = list(await ctx.session.scalars(select(Todo).where(Todo.patient_id.in_(ids), Todo.due_date == today(),
                                                             Todo.status.in_(["todo", "in_progress"])).order_by(Todo.due_time)))
    t = now()
    due = [x for x in rows if (t - at_local(x.due_date, x.due_time)).total_seconds() >= 30 * 60]
    return due or (rows[:1] if any_open else [])


def checkin_prompt(ctx: Ctx, todo: Todo) -> str:
    p = ctx.patients[todo.patient_id]
    return f"Was <b>{ctx.first(p)}'s {todo.title.lower()}</b> ({todo.due_time.strftime('%-I:%M %p')}) done?"


def checkin_buttons(ctx: Ctx, todo: Todo) -> None:
    ctx.qr("Completed", "checkin_status", todo_id=str(todo.id), status="done")
    ctx.qr("Not done", "checkin_status", todo_id=str(todo.id), status="not_done")
    ctx.qr("Skipped", "checkin_status", todo_id=str(todo.id), status="skipped")


async def run_action(ctx: Ctx, action: str, payload: dict) -> str:
    """Returns assistant text (HTML-lite). Cards/quick replies are accumulated on ctx."""
    s = ctx.session
    if action == "checkin_start":
        todos = await due_checkins(ctx, any_open=True)
        if not todos:
            return "Nothing is waiting for a check-in right now."
        checkin_buttons(ctx, todos[0])
        return checkin_prompt(ctx, todos[0])

    if action == "checkin_status":
        todo = await _todo(ctx, payload["todo_id"])
        p = ctx.patients[todo.patient_id]
        if payload["status"] == "done":
            await todo_svc.set_status(s, ctx.memory, ctx.user, todo, "done")
            ctx.board_changed = True
            return f"Marked done and saved to {ctx.first(p)}'s memory."
        ctx.active = p
        for r in todo_svc.REASONS:
            ctx.qr(r, "todo_reason", todo_id=str(todo.id), status=payload["status"], reason=r)
        return "What happened?"

    if action == "todo_reason":
        todo = await _todo(ctx, payload["todo_id"])
        r = payload["reason"]
        detail = payload.get("detail")
        if not payload.get("final") and not detail and DETAIL.get(r):
            for d in DETAIL[r]:
                ctx.qr(d, "todo_reason", todo_id=str(todo.id), status=payload["status"], reason=r,
                       detail="" if d == "Skip detail" else d.lower(), final=True)
            return "Anything to add? (or type it)"
        reason = r.lower() + (f", {detail}" if detail else "")
        return await _finish_status(ctx, todo, payload["status"], reason)

    if action == "accept_suggestion" or action == "dismiss_suggestion":
        sug = await s.get(Suggestion, uuid.UUID(payload["id"]))
        if not sug or sug.patient_id not in ctx.patients:
            return "I couldn't find that suggestion."
        accept = action == "accept_suggestion"
        await decide(s, ctx.memory, ctx.user, sug, accept)
        p = ctx.patients[sug.patient_id]
        if sug.kind == "reschedule":
            ctx.board_changed = True
            return (f"Done. From tomorrow, {ctx.first(p)}'s task is at {sug.params.get('new_time')}. I've remembered why."
                    if accept else "Okay, keeping the current time. I'll keep track of how it goes.")
        if accept:
            kw = sug.params.get("keyword") or "walk"
            t = await s.scalar(select(Todo).where(Todo.patient_id == p.id, Todo.due_date == today(), Todo.status == "todo",
                                                  Todo.title.ilike(f"%{kw}%")))
            if t:
                await todo_svc.set_status(s, ctx.memory, ctx.user, t, "in_progress", "Started because she is restless")
                ctx.board_changed = True
            return "Moved it to Now. Tell me how it goes and I'll remember the outcome."
        return "Okay."

    if action == "save_logs":
        out = await _save_drafts(ctx, payload["entries"])
        return out
    if action == "ask":
        from app.agent.rules import answer_question

        p = ctx.patient(payload["patient_id"])
        ctx.active = p
        return await answer_question(ctx, p, payload["question"])
    if action == "edit_logs":
        return "Tell me what to change, and I'll prepare the entries again."
    if action == "dismiss":
        return "Okay."
    raise ValueError(f"Unknown action {action}")


async def _todo(ctx: Ctx, todo_id: str) -> Todo:
    t = await ctx.session.get(Todo, uuid.UUID(todo_id))
    if not t or t.patient_id not in ctx.patients:
        raise PermissionError("Todo not in your assignments")
    return t


async def _finish_status(ctx: Ctx, todo: Todo, status: str, reason: str) -> str:
    res = await todo_svc.set_status(ctx.session, ctx.memory, ctx.user, todo, status, reason)
    ctx.board_changed = True
    p = ctx.patients[todo.patient_id]
    ctx.use([])
    if res.suggestion:
        T.add_suggestion_card(ctx, res.suggestion, p)
        n = len(res.suggestion.evidence) - 1
        return (f"Saved. This is the <b>{_ord(n)} time</b> in a week {ctx.first(p)}'s {todo.title.lower()} wasn't done."
                if n >= 2 else "Saved.") + " Here's what I found in memory:"
    if res.coordinator_hint:
        return "Saved. " + res.coordinator_hint
    msg = f"Saved. I'll remember this for {ctx.first(p)}."
    if reason.startswith("unwell"):
        msg += " If they seem unwell, follow the care plan and inform the coordinator."
    return msg


async def _save_drafts(ctx: Ctx, entries: list[dict]) -> str:
    saved, extras, sugg = 0, [], None
    marked: list[str] = []
    for e in entries:
        p = ctx.patient(e["patient_id"])
        r = await log_svc.save_log(ctx.session, ctx.memory, ctx.user, p, category=e["category"], structured=e.get("structured", {}),
                                   narrative=e.get("narrative", ""), severity=e.get("severity", "normal"),
                                   observed_at=aware(datetime.fromisoformat(e["observed_at"])) if e.get("observed_at") else None)
        saved += 1
        ctx.board_changed = ctx.board_changed or bool(r.todo_marked)
        if r.todo_marked:
            marked.append(r.todo_marked.title)
        for a in r.new_alerts:
            extras.append(f"I've flagged it for the coordinator: {a.summary.split(' This is')[0]}")
        if r.urgent:
            ctx.escalated = True
        sugg = sugg or r.suggestion
        last = p
    msg = f"Saved {saved} {'entry' if saved == 1 else 'entries'} to {ctx.first(last)}'s record and memory."
    if marked:
        msg += " Marked done: " + ", ".join(marked) + "."
    if extras:
        msg += " " + " ".join(extras)
    if sugg:
        T.add_suggestion_card(ctx, sugg, last)
        ctx.use([])
        msg += " Something that has helped before:"
    return msg


def _ord(n: int) -> str:
    return {1: "1st", 2: "2nd", 3: "3rd"}.get(n, f"{n}th")
