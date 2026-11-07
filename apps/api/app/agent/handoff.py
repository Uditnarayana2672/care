"""W5 — handoff briefing: care plan first (PostgreSQL), then cited memory, then open items."""
from sqlalchemy import select

from app.agent.context import Ctx
from app.core.time import fmt_day, today
from app.models import Alert, Allergy, Medication, Patient, Suggestion, Todo
from app.services.facts import evidence_line


def cite(item) -> str:
    d = fmt_day(item.occurred_at) if item.occurred_at else ""
    return f"{item.caretaker_name or 'caretaker'}, {d}".strip(", ")


async def build_handoff(ctx: Ctx, p: Patient) -> tuple[str, list[dict]]:
    s = ctx.session
    rows: list[dict] = []
    first = ctx.first(p)
    allergies = list(await s.scalars(select(Allergy).where(Allergy.patient_id == p.id)))
    plan = f"{p.mobility_level or 'Mobility not recorded'}. {p.diet_type or ''}".strip()
    ver = [a.substance for a in allergies if a.verification == "verified"]
    if ver:
        plan += f" Allergy: {', '.join(ver)} (verified)."
    rows.append({"label": "Care plan", "text": plan})
    meds = list(await s.scalars(select(Medication).where(Medication.patient_id == p.id, Medication.verification == "verified")))
    med_txt = "; ".join(f"{m.name} {m.strength} at {', '.join(m.scheduled_times)} (verified)" for m in meds) or "No verified medicines on record."
    ans = await ctx.memory.reflect(p, "handoff essentials: what must a new caretaker know before the next shift?", budget="mid")
    ctx.use(ans.items)
    pool = list(ans.items)
    for q in ("medication taken easily warm water nausea", "recent sleep diet mood changes"):
        extra = await ctx.memory.recall(p, q, types=["world", "experience"], max_tokens=1500)
        pool += [i for i in extra if i.id not in {x.id for x in pool}]
    recall_all = pool
    warm = next((i for i in sorted(pool, key=lambda i: i.occurred_at or 0, reverse=True)
                 if "warm water" in i.text.lower()), None)
    if warm:
        ctx.use([warm])
    if warm:
        med_txt += f" Takes it better with warm water — {cite(warm)}."
    rows.append({"label": "Medicine", "text": med_txt})
    alerts = list(await s.scalars(select(Alert).where(Alert.patient_id == p.id, Alert.status.in_(["open", "acknowledged"]),
                                                      Alert.kind.in_(["trend", "urgent_log", "escalation", "missed_med"]))))
    if alerts:
        rows.append({"label": "Watch", "text": " ".join(f"{a.summary.split(' This is')[0]} — trend watch, {fmt_day(a.created_at)}." for a in alerts)})
    if ctx.memory.enabled:
        obs = await ctx.memory.observations(p, "helps calm restless")
        ctx.use(obs)
        helps = [o for o in obs if o.pattern_kind == "helps"]
        for o in helps[:2]:
            who = sorted({e.caretaker_name for e in o.evidence if e.caretaker_name})
            rows.append({"label": "What helps", "text": f"{o.text} — {o.proof_count} times, {' & '.join(who)}."})
        changes = list(await s.scalars(select(Suggestion).where(Suggestion.patient_id == p.id, Suggestion.kind == "reschedule",
                                                                Suggestion.status == "accepted")))
        for c in changes[-2:]:
            rows.append({"label": "Changed", "text": f"{c.title.rstrip('?')} — {c.params.get('decided_by', '')}, {fmt_day(c.created_at)}."})
    pend = [a for a in allergies if a.verification == "pending"]
    open_todos = list(await s.scalars(select(Todo).where(Todo.patient_id == p.id, Todo.due_date == today(),
                                                         Todo.status.in_(["todo", "in_progress"])).order_by(Todo.due_time)))
    opens = [f"{a.substance} ({a.reaction or 'reported'}): pending coordinator check" for a in pend]
    opens += [f"{t.title} at {t.due_time.strftime('%H:%M')}" for t in open_todos[:4]]
    if opens:
        rows.append({"label": "Open", "text": "; ".join(opens)})
    if not ctx.memory.enabled or not (recall_all or ans.items):
        msg = (f"Here is what the care plan says for {first}. I don't have remembered history to add beyond it — "
               "please ask the previous caretaker or the coordinator.")
    else:
        msg = f"Here's {first} for tonight. Care plan first, then what previous caretakers observed:"
    return msg, rows


def evidence_for(items) -> list[dict]:
    return [evidence_line(i) for i in items]
