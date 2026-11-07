"""Pattern keys attached to retained facts so the local backend can consolidate observations.

Hindsight does this server-side; the local backend mimics it deterministically from metadata.
"""
import re

KINDS = {"helps": "What helps", "fails": "Why todos fail", "routine": "Routine", "constraint": "Timing constraint"}


def derive_pattern(category: str, structured: dict, narrative: str) -> tuple[str, str, str] | None:
    """Returns (pattern_key, observation_text, pattern_kind) or None."""
    s = (narrative + " " + " ".join(str(v) for v in structured.values())).lower()
    if category in ("mood", "observation") and re.search(r"walk", s) and re.search(
        r"calm|settled|slept|better|improved", s
    ):
        return ("evening-walk-calms", "An assisted evening walk calms the patient when restless or anxious", "helps")
    if category == "medication" and re.search(r"warm water", s):
        return ("med-warm-water", "Takes medicine more easily with warm water", "routine")
    if category in ("diet", "mood", "observation") and re.search(r"lunch", s) and re.search(
        r"late|delay", s
    ) and re.search(r"anxious|upset|restless|agitated|pacing", s):
        return ("late-lunch-anxious", "Becomes anxious when lunch is served late", "constraint")
    return None


def todo_pattern(title: str, status: str, reason: str, note: str = "") -> tuple[str, str, str] | None:
    if status in ("not_done", "skipped"):
        r = (reason or "").lower().strip()
        r = re.sub(r"\W+", "-", r)[:30] or "unspecified"
        if "cold" in (reason + note).lower():
            return (f"todo-fail:{title.lower()}:cold", f"'{title}' is often refused: the patient says it feels cold", "fails")
        return (f"todo-fail:{title.lower()}:{r}", f"'{title}' is often not done because: {reason or 'unspecified'}", "fails")
    return None
