import uuid
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import Cookie, Depends, Header, HTTPException, Path
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_session
from app.models import Assignment, AuditEvent, Patient, User

COOKIE = "cb_session"


def make_token(user: User) -> str:
    payload = {"sub": str(user.id), "role": user.role, "exp": datetime.now(UTC) + timedelta(days=7)}
    return jwt.encode(payload, get_settings().jwt_secret, algorithm="HS256")


async def get_current_user(
    session: AsyncSession = Depends(get_session),
    cb_session: str | None = Cookie(default=None),
    authorization: str | None = Header(default=None),
) -> User:
    token = cb_session
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:]
    if not token:
        raise HTTPException(401, "Not signed in")
    try:
        data = jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"])
        user = await session.get(User, uuid.UUID(data["sub"]))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(401, "Invalid session") from e
    if not user:
        raise HTTPException(401, "Unknown user")
    return user


def require_role(*roles: str):
    async def dep(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles and user.role != "admin":
            raise HTTPException(403, "Not allowed for your role")
        return user

    return dep


async def assigned_patient_ids(session: AsyncSession, user: User) -> list[uuid.UUID]:
    if user.role in ("coordinator", "admin"):
        rows = await session.scalars(select(Patient.id).where(Patient.org_id == user.org_id))
        return list(rows)
    rows = await session.scalars(
        select(Assignment.patient_id).where(Assignment.user_id == user.id, Assignment.active.is_(True))
    )
    return list(rows)


async def check_assignment(session: AsyncSession, user: User, patient_id: uuid.UUID) -> Patient:
    patient = await session.get(Patient, patient_id)
    if not patient or patient.org_id != user.org_id:
        raise HTTPException(404, "Patient not found")
    if user.role in ("coordinator", "admin"):
        return patient
    ok = await session.scalar(
        select(Assignment.id).where(
            Assignment.patient_id == patient_id, Assignment.user_id == user.id, Assignment.active.is_(True)
        )
    )
    if not ok:
        raise HTTPException(403, "You are not assigned to this patient")
    return patient


async def require_assignment(
    patient_id: uuid.UUID = Path(...),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Patient:
    return await check_assignment(session, user, patient_id)


async def audit(session: AsyncSession, user: User | None, action: str, patient_id=None, **detail) -> None:
    session.add(AuditEvent(user_id=user.id if user else None, action=action, patient_id=patient_id, detail=detail))
