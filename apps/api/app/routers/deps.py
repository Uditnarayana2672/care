from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user
from app.core.db import get_session
from app.memory.service import MemoryService, get_memory
from app.models import User


def memory_dep() -> MemoryService:
    return get_memory()


async def optional_user(request: Request, session: AsyncSession = Depends(get_session)) -> User | None:
    try:
        return await get_current_user(session=session, cb_session=request.cookies.get("cb_session"),
                                      authorization=request.headers.get("authorization"))
    except Exception:  # noqa: BLE001
        return None
