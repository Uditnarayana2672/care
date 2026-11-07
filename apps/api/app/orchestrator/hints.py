"""Memory-derived scheduling hints (routine-and-timing), cached per patient. Time windows / emphasis only —
never adds or alters medications."""
import re

from app.core import events
from app.memory.service import MemoryService
from app.models import Patient

RULES = [
    # (regex on observation text, hint)
    (r"lunch.*late|late.*lunch|anxious.*(lunch|meal)", {"category": "meal", "title": r"lunch", "boost": 15,
                                                         "reason": "First: gets anxious if lunch is late"}),
    (r"walk.*(calm|settle|helps?)|calm.*walk", {"category": "mobility", "title": r"walk", "boost": 8,
                                                  "reason": "Helps her settle before bed"}),
    (r"warm water", {"category": "medication", "title": r".", "boost": 3, "reason": "Verified · give with warm water",
                     "enrich_only": True}),
]


def hints_from_observations(obs) -> list[dict]:
    out = []
    for o in obs:
        for rx, h in RULES:
            if re.search(rx, o.text, re.I):
                out.append({**h, "proof": o.proof_count, "chip": f"observed {o.proof_count}×" if o.proof_count else "learned"})
    return out


async def refresh_hints(memory: MemoryService, patient: Patient) -> list[dict]:
    obs = await memory.observations(patient, "")
    hints = hints_from_observations(obs)
    await events.cache_set(f"hints:{patient.id}", hints)
    return hints


async def get_hints(memory: MemoryService, patient: Patient) -> list[dict]:
    if not memory.enabled:
        return []
    cached = await events.cache_get(f"hints:{patient.id}")
    if not cached:
        cached = await refresh_hints(memory, patient)
    return cached


async def invalidate(patient: Patient) -> None:
    await events.cache_set(f"hints:{patient.id}", None)
