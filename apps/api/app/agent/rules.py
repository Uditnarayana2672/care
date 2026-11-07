"""Deterministic driver: intent routing + extraction that calls the same tools as the LLM driver.
Used when GROQ_API_KEY is absent, and as the fallback when the LLM misbehaves."""
import re
import uuid
from datetime import datetime, timedelta

from sqlalchemy import select

from app.agent import tools as T
from app.agent.actions import checkin_buttons, checkin_prompt, due_checkins
from app.agent.context import Ctx
from app.agent.handoff import build_handoff
from app.core.config import get_settings
from app.core.time import aware, local_now, today
from app.models import Medication, Patient, Todo
from app.services.facts import evidence_line

HANDOFF = re.compile(r"taking over|take over|handover|hand over|what should i know|need to know|brief me|handoff", re.I)
LOGGY = re.compile(r"\b(gave|given|slept|sleep|ate|eaten|dinner|lunch|breakfast|tablet|refused|restless|anxious|agitated|calm|rash|nause\w*|fell|fall)\b", re.I)
HELP = re.compile(r"what (usually |has |worked|helps)|what helps|what worked", re.I)
CHECK = re.compile(r"\b(check ?in|any todos?|todos? to check|was .* done)\b", re.I)
MOODS = {"restless": "restless", "anxious": "anxious", "agitated": "restless", "calm": "calm", "happy": "happy", "low": "low",
         "confused": "confused", "sad": "low"}
PORTION = [(r"\bhalf\b", "half"), (r"\bonly (a )?(little|bit)|\ba little\b|\blittle\b", "little"), (r"\bnothing|didn'?t eat|refused (her|his) (meal|dinner|lunch)", "none"),
           (r"\ball\b|\bfull\b|\bwhole\b|\bfinished\b", "full")]


def resolve_patient(ctx: Ctx, text: str) -> Patient | None:
    hits = [p for p in ctx.patients.values() if re.search(rf"\b{re.escape(p.full_name.split()[0])}\b", text, re.I)
            or re.search(rf"\b{re.escape(p.full_name.split()[-1])}\b", text, re.I)]
    if len(hits) == 1:
        return hits[0]
    if ctx.active:
        return ctx.active
    if len(ctx.patients) == 1:
        return next(iter(ctx.patients.values()))
    return None


def _time_hint(text: str, base: datetime) -> datetime:
    m = re.search(r"\bat (\d{1,2})(?::(\d{2}))?\s*(am|pm)?", text, re.I)
    if not m:
        return base
    h, mi, ap = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "").lower()
    if ap == "pm" and h < 12:
        h += 12
    elif not ap and h < 7:
        h += 12
    return base.replace(hour=h % 24, minute=mi, second=0, microsecond=0)


async def extract_entries(ctx: Ctx, p: Patient, text: str) -> list[dict]:
    local = local_now()
    meds = list(await ctx.session.scalars(select(Medication).where(Medication.patient_id == p.id, Medication.verification == "verified")))
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n", text) if s.strip()]
    entries: list[dict] = []
    for sent in sentences:
        low = sent.lower()
        base = {"patient_id": p.id, "observed_at": local}
        med = next((m for m in meds if m.name.lower() in low), None)
        if med and re.search(r"gave|given|took|taken|refus|missed|held", low):
            status = "refused" if "refus" in low else "missed" if "missed" in low else "held" if "held" in low else "given"
            eff = None
            m = re.search(r"(?:she|he|they)\s+(felt|had|got)\s+(.*?)(?:\.|$)", sent, re.I)
            if m:
                eff = m.group(2).strip()
            entries.append({**base, "category": "medication", "narrative": sent,
                            "structured": {"medication_id": str(med.id), "medication_name": med.name, "status": status,
                                           "time": _time_hint(sent, local).strftime("%H:%M"), "observed_effects": eff},
                            "severity": "normal", "observed_at": _time_hint(sent, local)})
            continue
        # compound sentences: "..., she felt nauseous for half an hour" attached to previous med entry
        if entries and entries[-1]["category"] == "medication" and re.match(r"(she|he)\s+(felt|had|got)\b", low):
            entries[-1]["structured"]["observed_effects"] = re.sub(r"^(she|he)\s+", "", sent, flags=re.I).rstrip(".")
            continue
        m = re.search(r"slept\s+(?:only\s+|about\s+|around\s+)?(?:maybe\s+)?(\d+(?:\.\d+)?)\s*(?:h|hr|hrs|hours?)?", low)
        if m or re.search(r"slept (badly|poorly|well)", low):
            hours = float(m.group(1)) if m else None
            q = "poor" if re.search(r"bad|poor|only|short", low) or (hours is not None and hours < 6) else "good" if "well" in low else "fair"
            entries.append({**base, "category": "sleep", "narrative": sent, "structured": {"hours": hours, "quality": q},
                            "severity": "watch" if q == "poor" else "normal", "observed_at": local})
            continue
        if re.search(r"\b(ate|eaten|dinner|lunch|breakfast)\b", low) and not re.search(r"\b(restless|anxious)\b", low):
            portion = next((v for rx, v in PORTION if re.search(rx, low)), "full")
            meal = next((w for w in ("breakfast", "lunch", "dinner") if w in low), "meal")
            ref = re.search(r"refused (?:the |her |his )?(\w+)", low)
            entries.append({**base, "category": "diet", "narrative": sent,
                            "structured": {"meal": meal, "portion": portion, "refused_items": ref.group(1) if ref else None},
                            "severity": "watch" if portion in ("little", "none") else "normal", "observed_at": local})
            continue
        if re.search(r"rash|allerg|hives|swelling|itch", low):
            sub = re.search(r"after (?:a |the |her |his )?(?:new )?([\w ]{3,30})", low)
            entries.append({**base, "category": "allergy", "narrative": sent,
                            "structured": {"substance": sub.group(1).strip() if sub else "unknown", "reaction": sent},
                            "severity": "watch", "observed_at": local})
            continue
        word = next((w for w in MOODS if re.search(rf"\b{w}\b", low)), None)
        if word:
            mood = MOODS[word]
            helped = "assisted walk" if "walk" in low else None
            entries.append({**base, "category": "mood", "narrative": sent,
                            "structured": {"mood": mood, "triggers": "after dinner" if "dinner" in low else None, "what_helped": helped},
                            "severity": "watch" if mood in ("restless", "anxious", "low", "confused") else "normal",
                            "observed_at": local - timedelta(minutes=0)})
            continue
        if re.search(r"\b(fell|fall|chest pain|breath|unresponsive|bleeding)\b", low):
            entries.append({**base, "category": "observation", "narrative": sent, "structured": {}, "severity": "urgent", "observed_at": local})
    return entries


def _entry_row(e: dict) -> tuple[str, str]:
    """Pretty row for the draft card. LLM drafts may omit structured keys → fall back to the narrative."""
    try:
        return _entry_row_structured(e)
    except (KeyError, TypeError, AttributeError, ValueError):
        return e["category"].capitalize(), e.get("narrative") or "—"


def _entry_row_structured(e: dict) -> tuple[str, str]:
    s, c = e["structured"], e["category"]
    if c == "medication":
        t = f"{s['medication_name']} · {s['status']} {aware(e['observed_at']).astimezone(get_settings().tz).strftime('%-I:%M %p') if hasattr(e['observed_at'], 'strftime') else ''}"
        return "Medication", t + (f" · observed: {s['observed_effects']}" if s.get("observed_effects") else "")
    if c == "sleep":
        return "Sleep", f"Last night ≈{s['hours']:g} h · quality {s['quality']}" if s.get("hours") else f"Quality {s['quality']}"
    if c == "diet":
        return "Diet", f"{s['meal'].capitalize()} · {s['portion']} portion" + (f" · refused {s['refused_items']}" if s.get("refused_items") else "")
    if c == "mood":
        return "Mood", f"{s['mood'].capitalize()}{' ' + s['triggers'] if s.get('triggers') else ''} · severity: {e['severity']}"
    return c.capitalize(), e["narrative"]


def is_structured(text: str) -> bool:
    """Handoffs and todo check-ins are button-driven workflows: always run them deterministically,
    even when an LLM is configured, so the UI flow (quick replies, cited handoff card) is reliable."""
    low = text.lower()
    return bool(HANDOFF.search(low) or (CHECK.search(low) and not LOGGY.search(low.replace("check", ""))))


async def drive(ctx: Ctx, text: str) -> str:
    low = text.lower()
    p = resolve_patient(ctx, text)
    if HANDOFF.search(low):
        if not p:
            return ask_patient(ctx, text)
        ctx.active = p
        msg, rows = await build_handoff(ctx, p)
        ctx.card({"type": "handoff", "title": f"Handoff · {p.full_name}", "rows": rows,
                  "note": "Learned context is not a clinical instruction. Follow the care plan."})
        ctx.qr("Does she take her night tablet easily?", "ask", question="Does she take her night tablet easily?", patient_id=str(p.id))
        ctx.qr("Who usually helps her sleep?", "ask", question="Who usually helps her sleep?", patient_id=str(p.id))
        return msg
    if CHECK.search(low) and not LOGGY.search(low.replace("check", "")):
        todos = await due_checkins(ctx, any_open=True)
        named = [x for x in ctx.patients.values() if x.full_name.split()[0].lower() in low]
        if named or re.search(r"bath|lunch|walk|dinner|breakfast", low):
            rows = list(await ctx.session.scalars(select(Todo).where(
                Todo.patient_id.in_([x.id for x in (named or ctx.patients.values())]), Todo.due_date == today(),
                Todo.status.in_(["todo", "in_progress"])).order_by(Todo.due_time)))
            words = [w for w in ("bath", "lunch", "walk", "dinner", "breakfast", "metformin", "bp") if w in low]
            hit = [t for t in rows if any(w in t.title.lower() for w in words)] or rows
            todos = hit or todos
        if not todos:
            return "Nothing is waiting for a check-in right now."
        checkin_buttons(ctx, todos[0])
        return checkin_prompt(ctx, todos[0])
    # reason typed after a not-done: "refused - said she feels cold"
    if HELP.search(low):
        if not p:
            return ask_patient(ctx, text)
        r = await T.what_worked(ctx, T.WhatWorkedArgs(patient_id=p.id, situation=text))
        return "Here is what has helped before:" if r.get("suggestion") else "I don't have enough repeated evidence yet. Please follow the care plan or ask the coordinator."
    if re.search(r"\?\s*$", text) or re.match(r"(does|did|how|when|who|what|why|is|has)\b", low):
        if not p:
            return ask_patient(ctx, text)
        return await answer_question(ctx, p, text)
    if LOGGY.search(low):
        if not p:
            return ask_patient(ctx, text)
        entries = await extract_entries(ctx, p, text)
        if not entries:
            return f"I couldn't pick out anything to record for {ctx.first(p)}. Could you rephrase?"
        for e in entries:
            await T.log_care(ctx, T.LogCareArgs(patient_id=p.id, category=e["category"], structured={k: v for k, v in e["structured"].items() if v is not None},
                                                narrative=e["narrative"], severity=e["severity"], observed_at=aware(e["observed_at"])))
        return f"I found <b>{len(entries)} {'entry' if len(entries) == 1 else 'entries'}</b> for {ctx.first(p)}. Save {'it' if len(entries) == 1 else 'them'}?"
    if p:
        return "Got it. Tell me what to log (medicine, sleep, food, mood), or ask for a handoff briefing."
    return ask_patient(ctx, text)


async def answer_question(ctx: Ctx, p: Patient, text: str) -> str:
    names = "|".join(re.escape(w) for w in p.full_name.split())
    q = re.sub(rf"\b({names}|she|he|her|his)\b", " ", text, flags=re.I)
    r = await T.ask_memory(ctx, T.AskMemoryArgs(patient_id=p.id, question=q))
    cites = r.get("citations") or []
    if not cites:
        return "Not enough information to say. You could ask the previous caretaker or the coordinator, or log what you observe tonight."
    top = cites[:3]
    lines = "".join(f"<br>• {c['text']} <i>({c['caretaker'] or 'caretaker'}, {c['date']})</i>" for c in top)
    return f"From memory:{lines}"


def ask_patient(ctx: Ctx, text: str) -> str:
    for p in ctx.patients.values():
        ctx.qr(p.full_name, "select_patient", patient_id=str(p.id), message=text)
    return "Which patient is this about?"


def draft_card(ctx: Ctx) -> None:
    if not ctx.drafts:
        return
    p = ctx.patient(ctx.drafts[0]["patient_id"])
    rows = []
    for d in ctx.drafts:
        e = {**d, "observed_at": datetime.fromisoformat(d["observed_at"])}
        lbl, txt = _entry_row(e)
        rows.append({"label": lbl, "text": txt})
    rows.append({"label": "By", "text": ctx.user.full_name.split()[0]})
    ctx.card({"type": "log_draft", "title": f"Save for {ctx.first(p)}", "rows": rows,
              "note": "I record what you observed. I can't advise on doses."})
    ctx.qr("Save all" if len(ctx.drafts) > 1 else "Save", "save_logs", entries=ctx.drafts)
    ctx.qr("Edit", "edit_logs")


__all__ = ["drive", "draft_card", "uuid", "evidence_line"]
