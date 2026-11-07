import os
import tempfile

_tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_tmp}/test.db"
os.environ["REDIS_URL"] = ""
os.environ["HINDSIGHT_API_KEY"] = ""
os.environ["GROQ_API_KEY"] = ""

import json  # noqa: E402

import httpx  # noqa: E402
import pytest_asyncio  # noqa: E402

from app.main import app  # noqa: E402
from app.seed.load import run  # noqa: E402


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def seeded():
    await run(reset=True)
    return True


@pytest_asyncio.fixture(loop_scope="session")
async def client(seeded):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t/api/v1") as c:
        yield c


async def login(client: httpx.AsyncClient, who: str) -> httpx.AsyncClient:
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t/api/v1")
    r = await c.post("/auth/demo-login", json={"email": f"{who}@carebridge.demo"})
    assert r.status_code == 200, r.text
    return c


def parse_sse(text: str) -> list[dict]:
    out, ev = [], None
    for line in text.splitlines():
        if line.startswith("event:"):
            ev = line[6:].strip()
        elif line.startswith("data:") and ev:
            out.append({"event": ev, "data": json.loads(line[5:].strip())})
    return out


async def chat(c, **body):
    r = await c.post("/chat", json=body)
    assert r.status_code == 200, r.text
    evs = parse_sse(r.text)
    text = "".join(e["data"]["text"] for e in evs if e["event"] == "token")
    return {
        "text": text, "events": evs,
        "cards": [e["data"] for e in evs if e["event"] == "card"],
        "quick": next((e["data"]["replies"] for e in evs if e["event"] == "quick_replies"), []),
        "memory": next((e["data"]["items"] for e in evs if e["event"] == "memory_used"), []),
    }


@pytest_asyncio.fixture(loop_scope="session")
async def anjali(seeded):
    c = await login(None, "anjali")
    yield c
    await c.aclose()


@pytest_asyncio.fixture(loop_scope="session")
async def rohan(seeded):
    c = await login(None, "rohan")
    yield c
    await c.aclose()


@pytest_asyncio.fixture(loop_scope="session")
async def meera(seeded):
    c = await login(None, "meera")
    yield c
    await c.aclose()
