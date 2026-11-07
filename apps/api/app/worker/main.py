import asyncio
import logging

from app.core.db import init_models
from app.worker.scheduler import build_scheduler

logging.basicConfig(level=logging.INFO)


async def main() -> None:
    await init_models()
    sch = build_scheduler()
    sch.start()
    logging.info("worker started: %s", [j.id for j in sch.get_jobs()])
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
