import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.db import init_models
from app.routers.api import router
from app.worker.scheduler import build_scheduler

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    if s.database_url.startswith("sqlite"):
        await init_models()
    sch = None
    if not s.redis_url:  # single-process dev: run the scheduler in the API
        sch = build_scheduler()
        sch.start()
    yield
    if sch:
        sch.shutdown(wait=False)


app = FastAPI(title="CareBridge API", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=get_settings().cors_origins.split(","), allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])
app.include_router(router, prefix="/api/v1")
