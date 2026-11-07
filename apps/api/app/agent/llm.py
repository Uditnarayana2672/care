"""LLM driver: Groq (OpenAI-compatible) with function calling, Pydantic-validated tool args."""
import html
import json
import logging
import re

from openai import AsyncOpenAI
from pydantic import ValidationError

from app.agent.context import Ctx
from app.agent.tools import TOOLS, openai_tools
from app.core.config import get_settings
from app.core.time import local_now
from app.services.facts import evidence_line

log = logging.getLogger(__name__)
MAX_CALLS = 6

SYSTEM = """You are CareBridge, an assistant for home caretakers of elderly patients.
You help caretakers log care, track todos, and continue care across handoffs.

Rules:
- Use tools for every fact about a patient. Never invent facts.
- Do not diagnose, prescribe, estimate or change medication doses, or explain medical causes.
- When you use memory, cite each item as (date, caretaker). Label learned patterns
  "Observed pattern — not a clinical instruction".
- If evidence is thin or conflicting, say so and suggest following the care plan or
  contacting the coordinator.
- When a log describes urgent signs (fall, chest pain, breathing difficulty, unresponsive),
  tell the caretaker to follow the emergency rule and call emergency services or the
  coordinator now, and raise an escalation.
- Only mention emergency steps when urgent signs are actually reported.
- Keep messages short: 2-5 sentences or a few "- " bullets. No tables, no headings, no emoji.
  Never show ids, uuids or bracketed reference codes; refer to evidence only as (date, caretaker).
- Only state today's todo status from "Today's todos". Past memory is history, not today's status.
- Always resolve which patient a message is about. If ambiguous, ask which patient.
- When the caretaker describes something that happened (medicine given, food, sleep, mood, symptoms),
  call log_care right away, once per entry. It only creates a draft; the app shows a Save button,
  so do not ask whether to save. Then reply with one sentence like "Drafted 2 entries for Asha — tap Save
  to confirm." Never say an entry is saved.
- A draft contains only what the caretaker said in their latest message. Never copy details from memory
  or earlier messages into structured fields or the narrative.
"""


class LLMUnavailable(Exception):
    pass


class _Invalid:
    def __init__(self, msg: str):
        self.msg = msg


_REFS = re.compile(r"\u3010[^\u3011]*\u3011|\s*\(?\b(?:id[:\s]*)?[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b\)?", re.I)


def to_html(text: str) -> str:
    text = _REFS.sub("", text)
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.M)
    t = html.escape(text)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    return t.replace("\n", "<br>")


async def _exec(ctx: Ctx, name: str, raw: str):
    if name not in TOOLS:
        return _Invalid(f"Unknown tool {name}")
    model, fn, _ = TOOLS[name]
    try:
        args = model.model_validate_json(raw or "{}")
    except (ValidationError, ValueError) as e:
        return _Invalid(f"Invalid arguments: {str(e)[:300]}")
    try:
        return await fn(ctx, args)
    except LookupError:
        return {"error": "Ask the caretaker which patient this is about."}
    except PermissionError as e:
        return {"error": str(e)}


async def drive_llm(ctx: Ctx, text: str, history: list[dict]) -> str:
    s = get_settings()
    client = AsyncOpenAI(api_key=s.groq_api_key, base_url="https://api.groq.com/openai/v1", timeout=40)
    list_fn = TOOLS["list_todos"]
    todos_view = await list_fn[1](ctx, list_fn[0]())
    evidence = ""
    if ctx.active and ctx.memory.enabled:
        items = await ctx.memory.recall(ctx.active, text)
        ctx.seen.update({i.id: i for i in items})
        evidence = "\nMemory evidence (date | caretaker | text):\n" + "\n".join(
            f"- {evidence_line(i)['date']} | {i.caretaker_name} | {i.text}" for i in items[:12])
    sys = SYSTEM + (
        f"\nNow: {local_now().strftime('%A %d %b %Y %H:%M')} (Asia/Kolkata). Caretaker: {ctx.user.full_name}.\n"
        f"Assigned patients: {json.dumps([{'id': str(p.id), 'name': p.full_name} for p in ctx.patients.values()])}\n"
        f"Active patient: {ctx.active.full_name + ' ' + str(ctx.active.id) if ctx.active else 'none'}\n"
        f"Today's todos: {json.dumps(todos_view['todos'])}{evidence}")
    msgs: list[dict] = [{"role": "system", "content": sys}, *history[-10:], {"role": "user", "content": text}]
    retried, calls = False, 0
    for model in (s.groq_model, s.groq_fallback_model):
        try:
            while True:
                resp = await client.chat.completions.create(model=model, messages=msgs, tools=openai_tools(),
                                                            tool_choice="auto" if calls < MAX_CALLS else "none", temperature=0.2)
                m = resp.choices[0].message
                if not m.tool_calls:
                    return to_html(m.content or "")
                msgs.append({"role": "assistant", "content": m.content or "", "tool_calls": [
                    {"id": c.id, "type": "function", "function": {"name": c.function.name, "arguments": c.function.arguments}}
                    for c in m.tool_calls]})
                for c in m.tool_calls:
                    calls += 1
                    result = await _exec(ctx, c.function.name, c.function.arguments)
                    if isinstance(result, _Invalid):
                        if retried:
                            raise LLMUnavailable("tool arguments invalid twice")
                        retried = True
                        result = {"error": result.msg}
                    msgs.append({"role": "tool", "tool_call_id": c.id, "content": json.dumps(result, default=str)})
        except LLMUnavailable:
            raise
        except Exception as e:  # noqa: BLE001
            log.warning("LLM %s failed: %s", model, e)
    raise LLMUnavailable("no model available")
