"""W9 — deterministic, explainable priority score + Kanban column."""
import re
from dataclasses import dataclass
from datetime import datetime

from app.core.time import at_local
from app.models import Alert, Todo

CAT_WEIGHT = {"medication": 25, "vitals": 20, "meal": 16, "hygiene": 10, "mobility": 8, "activity": 6, "other": 4}
ALERT_CATS = {"diet": {"meal"}, "sleep": {"mobility", "other", "activity"}, "mood": {"activity", "mobility", "other"},
              "medication": {"medication"}, "urgent": set(CAT_WEIGHT), "allergy": set()}
ALERT_LABEL = {"diet": "Open alert: reduced intake", "sleep": "Open alert: short sleep", "mood": "Open alert: low mood",
               "medication": "Open alert: refused medicine", "urgent": "Open urgent alert"}


@dataclass
class Scored:
    score: int
    reason: str
    column: str
    chip: str


def time_urgency(minutes: float) -> int:
    if minutes <= 0:
        return 40
    if minutes <= 60:
        return 35 - int(minutes / 60 * 5)
    if minutes <= 180:
        return 30 - int((minutes - 60) / 120 * 15)
    return max(0, 15 - int((minutes - 180) / 60))


def column_for(todo: Todo, minutes: float) -> str:
    if todo.status == "done":
        return "done"
    if todo.status in ("not_done", "skipped"):
        return "not_done"
    if todo.status == "in_progress" or minutes <= 60:
        return "now"
    return "next" if minutes <= 180 else "later"


def score_todo(todo: Todo, now: datetime, alerts: list[Alert], hints: list[dict], note: str = "") -> Scored:
    due = at_local(todo.due_date, todo.due_time)
    minutes = (due - now).total_seconds() / 60
    tu, cw = time_urgency(minutes), CAT_WEIGHT.get(todo.category, 4)
    ab, alabel = 0, ""
    for a in alerts:
        sig = a.signal or ("urgent" if a.kind == "urgent_log" else "")
        if todo.category in ALERT_CATS.get(sig, set()):
            ab, alabel = max(ab, 20 if sig in ("diet", "medication", "urgent") else 10), ALERT_LABEL.get(sig, "Open alert")
    mb, mreason, chip = 0, "", ""
    for h in hints:
        if h["category"] == todo.category and re.search(h["title"], todo.title, re.I):
            if not h.get("enrich_only"):
                mb = max(mb, h["boost"])
            if h["boost"] >= (mb if not h.get("enrich_only") else 0):
                mreason, chip = h["reason"], h["chip"]
    score = tu + cw + ab + mb
    if todo.status == "done":
        reason = todo.status_note or "Done"
    elif todo.status in ("not_done", "skipped"):
        reason = f"Not done: {todo.status_note.lower()}" if todo.status_note else "Not done"
    elif mreason:
        reason = mreason
    elif alabel:
        reason, chip = alabel, chip or "trend"
    elif minutes <= 0:
        reason = "Overdue · check-in pending"
    elif todo.category == "medication":
        reason = "Verified medication order" + (f" · {note}" if note else "")
    else:
        reason = note or "Care plan item"
    return Scored(score, reason, column_for(todo, minutes), chip)
