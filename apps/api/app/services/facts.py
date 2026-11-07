"""Compose factual, attributed, timestamped memory sentences (architecture §6.2)."""
from app.core.config import get_settings
from app.core.time import aware, fmt_dt
from app.models import CareLog, Patient, Todo, User

CONTEXT_BY_CATEGORY = {
    "medication": "medication_effect", "sleep": "sleep", "diet": "diet", "mood": "mood",
    "mobility": "mobility", "progress": "progress", "allergy": "allergy_report", "observation": "observation",
}


def first(p: Patient) -> str:
    return p.full_name.split()[0]


def todo_outcome_fact(patient: Patient, todo: Todo, who: User, status: str, reason: str, at) -> str:
    label = {"done": "DONE", "not_done": "NOT DONE", "skipped": "SKIPPED", "in_progress": "STARTED", "todo": "REOPENED"}[status]
    base = f"On {fmt_dt(at)}, caretaker {who.full_name.split()[0]} marked '{todo.title}' for {patient.full_name} {label}"
    if status in ("not_done", "skipped"):
        return f"{base}. Reason: {reason or 'not given'}."
    return f"{base} (scheduled {todo.due_time.strftime('%H:%M')})." + (f" {reason}" if reason else "")


def log_fact(patient: Patient, log: CareLog, who: User) -> tuple[str, str]:
    """Returns (text, context)."""
    s, when, name = log.structured or {}, fmt_dt(log.observed_at), who.full_name.split()[0]
    cat = log.category
    ctx = CONTEXT_BY_CATEGORY.get(cat, "observation")
    n = (log.narrative or "").strip().rstrip(".")
    if cat == "medication":
        med = s.get("medication_name", "medication")
        text = f"{when} — {med} {s.get('status', 'given')} by {name}."
        if s.get("observed_effects"):
            text += f" Observed: {s['observed_effects']}."
        elif n:
            text += f" {n}."
    elif cat == "sleep":
        text = f"Night of {fmt_dt(log.observed_at).rsplit(' ', 1)[0]}: slept ~{s.get('hours', '?')} hours"
        if s.get("wake_ups") is not None:
            text += f", woke {s['wake_ups']} times"
        text += f". Reported by {name}."
        if n:
            text += f" {n}."
    elif cat == "diet":
        text = f"{when} {s.get('meal', 'meal')}: ate {s.get('portion', 'some')} portion"
        if s.get("refused_items"):
            text += f", refused {s['refused_items']}"
        text += f". Reported by {name}."
    elif cat == "mood":
        helped = s.get("what_helped")
        ctx = "intervention_outcome" if helped else "mood"
        text = f"{when} — {name} logged mood {s.get('mood', '')}: {n or s.get('triggers', '')}."
        if helped:
            text += f" What helped: {helped}."
    elif cat == "allergy":
        text = f"Caretaker {name} reported {n or s.get('reaction', 'a reaction')} on {fmt_dt(log.observed_at)} (pending verification)."
    else:
        text = f"{when} — {name} logged ({cat}): {n}."
    if log.severity != "normal":
        text += f" Severity: {log.severity}."
    return text.replace("..", "."), ctx


def evidence_line(item) -> dict:
    who = item.caretaker_name
    when = item.occurred_at
    text = item.text
    if item.evidence:  # consolidated observation: attribute to its supporting facts
        who = " & ".join(sorted({e.caretaker_name for e in item.evidence if e.caretaker_name}))
        dated = [e.occurred_at for e in item.evidence if e.occurred_at]
        when = max(dated, key=aware) if dated else when
        text = f"{item.text} ({item.proof_count}×)" if item.proof_count else item.text
    elif getattr(item, "brief", ""):
        text = item.brief
    return {
        "id": item.id,
        "date": aware(when).astimezone(get_settings().tz).strftime("%Y-%m-%d") if when else "",
        "caretaker": who,
        "text": text,
    }
