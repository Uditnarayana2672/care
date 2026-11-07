import uuid
from typing import Literal

from pydantic import BaseModel, Field


class DemoLogin(BaseModel):
    email: str


class MedIn(BaseModel):
    name: str = Field(min_length=1)
    strength: str = ""
    times: list[Literal["morning", "afternoon", "night"]] = Field(default_factory=list)


class AllergyIn(BaseModel):
    substance: str
    reaction: str = ""


class ContactIn(BaseModel):
    name: str = ""
    relation: str = ""
    phone: str = ""


class RoutineIn(BaseModel):
    wake: str = "06:30"
    sleep: str = "21:30"
    breakfast: str = "08:00"
    lunch: str = "13:00"
    dinner: str = "19:30"
    likes: list[str] = Field(default_factory=list)


class EnrollmentIn(BaseModel):
    full_name: str = Field(min_length=2)
    age: int = Field(ge=18, le=120)
    gender: str = ""
    preferred_language: str = "English"
    phone: str = ""
    address: str = ""
    emergency_contact: ContactIn = ContactIn()
    conditions: list[str] = Field(default_factory=list)
    mobility_level: str = ""
    diet: list[str] = Field(default_factory=list)
    hearing_vision: str = ""
    medications: list[MedIn] = Field(default_factory=list)
    allergies: list[AllergyIn] = Field(default_factory=list)
    routine: RoutineIn = RoutineIn()
    source: Literal["self", "family"] = "self"


class StatusIn(BaseModel):
    status: Literal["todo", "in_progress", "done", "not_done", "skipped"]
    reason: str = ""


class ChatIn(BaseModel):
    message: str | None = None
    patient_id: uuid.UUID | None = None
    action: str | None = None
    payload: dict = Field(default_factory=dict)


class VerifyIn(BaseModel):
    kind: Literal["medication", "allergy"]
    decision: Literal["verified", "rejected"]


class MemoryToggleIn(BaseModel):
    enabled: bool | None = None
    question: str | None = None
    patient_id: uuid.UUID | None = None
