"""Safety guard: input + output validation. Regex first; optional LLM check hook."""
import re
from dataclasses import dataclass

DOSE_ASK = re.compile(r"\b(increase|decrease|double|halve|reduce|raise|skip|stop|change)\b.{0,30}\b(dose|dosage|mg|tablet|pill|medication|medicine)\b|\bhow (much|many)\b.{0,25}\b(mg|tablet|pill|dose)\b|\bshould (i|we) (give|increase|stop)\b.{0,30}\b(more|extra|double)\b", re.I)
DIAG_ASK = re.compile(r"\b(diagnos\w*|what (disease|condition|illness)|is it (diabetes|dementia|infection|stroke)|why is (she|he) (so )?(sick|ill)|what causes?)\b", re.I)
DOSE_OUT = re.compile(r"\b(increase|decrease|double|reduce|raise|lower)\b.{0,25}\b(dose|dosage)\b|\b\d+\s?(mg|mcg|ml)\b.{0,25}\b(instead|more|extra|should)\b|\byou should (take|give)\b.{0,30}\b\d+\s?(mg|tablet|pill)", re.I)
DIAG_OUT = re.compile(r"\b(likely|probably|may be|might be|could be) (caused by|due to|a sign of|diabetes|an? infection|dementia|depress)|\bthis (indicates|suggests|means) (that )?(she|he|the patient) (has|is suffering)|\bdiagnos(is|ed with)\b", re.I)
URGENT = re.compile(r"\b(fall|fell|fallen|chest pain|can'?t breathe|breathing (difficulty|trouble)|short of breath|unresponsive|unconscious|bleeding|collapsed)\b", re.I)

REFUSE_DOSE = ("I can't advise on medicine doses or changes. Please follow the prescription and contact the "
               "coordinator or doctor.")
REFUSE_DIAG = ("I can't diagnose or explain medical causes. I can log what you observed and flag it to the "
               "coordinator or doctor.")
EMERGENCY = ("This may be urgent. Follow the emergency rule now: call emergency services (112) or the coordinator "
             "immediately. I've raised an escalation.")


@dataclass
class InputVerdict:
    blocked: bool
    reply: str = ""
    urgent: bool = False


def check_input(text: str) -> InputVerdict:
    if URGENT.search(text):
        return InputVerdict(False, urgent=True)
    if DOSE_ASK.search(text):
        return InputVerdict(True, REFUSE_DOSE)
    if DIAG_ASK.search(text):
        return InputVerdict(True, REFUSE_DIAG)
    return InputVerdict(False)


def check_output(text: str, cards: list[dict]) -> tuple[str, list[dict], list[str]]:
    """Returns (text, cards, violations). Uncited suggestion cards are dropped."""
    violations: list[str] = []
    if DOSE_OUT.search(text):
        violations.append("dose")
        text = REFUSE_DOSE
    elif DIAG_OUT.search(text):
        violations.append("diagnosis")
        text = REFUSE_DIAG
    kept = []
    for c in cards:
        if c.get("type") == "suggestion" and not c.get("evidence"):
            violations.append("uncited_suggestion")
            continue
        blob = " ".join(str(v) for v in c.values())
        if DOSE_OUT.search(blob) or DIAG_OUT.search(blob):
            violations.append("card_content")
            continue
        kept.append(c)
    return text, kept, violations
