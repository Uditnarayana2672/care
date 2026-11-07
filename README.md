# CareBridge

**A chat-first care assistant for home caretakers of elderly patients, with memory that carries over between shifts.**

Caretakers log care and check off todos by chatting. Every outcome becomes an attributed, timestamped memory, so the next caretaker on shift sees what happened, what was refused and what has helped before. Over time the assistant learns patterns for each patient, for example *"Asha refuses her bath when it feels cold"*. It then proposes better schedules and gives cited handoff briefings.

Memory is powered by [**Hindsight**](https://vectorize.io) (by Vectorize). The LLM agent runs on **Groq**.

> ⚠️ **Synthetic data only.** CareBridge is a demo. It does not diagnose, prescribe or give dosing advice (see [Safety](#safety)).

---

## Contents

- [Features](#features)
- [Architecture](#architecture)
- [Quick start (Docker)](#quick-start-docker)
- [Run without Docker](#run-without-docker)
- [Configuration](#configuration)
- [Demo walkthrough](#demo-walkthrough)
- [Testing](#testing)
- [Project structure](#project-structure)
- [How CareBridge uses Hindsight](#how-carebridge-uses-hindsight)
- [Safety](#safety)
- [Further reading](#further-reading)

---

## Features

| Workflow | What it does |
| --- | --- |
| **W1–W2 Enrollment** | A 5-step wizard enrolls a patient. It creates their memory bank and sends self-reported medications to a coordinator for verification. |
| **W3 Check-ins** | Asks "Was Asha's bath done?" when a todo is 30 minutes overdue. Buttons record *Completed / Not done / Skipped* and the reason. |
| **W4 Chat logging** | Turns "Gave her metformin at dinner, ate half her rice" into structured draft entries the caretaker confirms with one tap. |
| **W5 Handoff** | "I'm taking over Asha tonight" returns a briefing, each point cited with caretaker and date. |
| **W6 What worked** | Suggests things that have helped before, but only when backed by repeated evidence (e.g. *"10-minute assisted walk, observed 3×"*). |
| **W7 Reschedule** | When a todo keeps failing for the same reason, proposes a new time with the supporting evidence. |
| **W8 Trends** | Rule-based alerts (short sleep, small portions, low mood, refused meds), always labelled *"an observation, not a diagnosis"*. |
| **W9 Smart board** | A Kanban board of today's todos, ordered by priority and annotated with learned reasons. |

There is also a **coordinator view** for verifying medications and handling alerts. A **Memory on/off comparison** shows the same question answered with and without history.

## Architecture

```mermaid
flowchart LR
  subgraph Browser
    W[Next.js 15 web app<br/>board · chat · enrollment]
  end
  subgraph Backend
    A[FastAPI API<br/>agent · guard · services]
    K[Worker<br/>APScheduler jobs]
  end
  W -- REST + SSE --> A
  A <--> P[(PostgreSQL 16)]
  A <--> R[(Redis 7<br/>events · cache)]
  K <--> P
  K -- publish check-ins --> R
  A -- retain / recall / reflect --> H[Hindsight Cloud<br/>one bank per patient]
  A -- tool calling --> G[Groq LLM]
```

- **Agent.** Handoffs and check-ins always use a deterministic flow with buttons. Free-form questions and logging go to the Groq LLM, which uses Pydantic-validated tool calls. If no key is set, or the LLM fails, a rule-based driver calls the same tools.
- **Guard.** Every reply is checked on the way out. It blocks diagnosis and dosing language, drops suggestions that have no evidence, and turns urgent words into an emergency instruction plus an escalation.
- **Offline fallbacks.** Each external dependency is optional, so the full demo runs on a laptop with no keys:

  | Dependency | When not configured |
  | --- | --- |
  | PostgreSQL | SQLite (`DATABASE_URL=sqlite+aiosqlite:///...`) |
  | Redis | In-process events and cache, with the scheduler inside the API |
  | Hindsight | Database-backed local memory backend (same interface) |
  | Groq | Deterministic rule-based agent |

## Quick start (Docker)

Requires Docker Desktop (or another Docker engine with Compose v2).

```bash
git clone https://github.com/Uditnarayana2672/care.git
cd care
cp .env.example .env          # optional: add GROQ_API_KEY / HINDSIGHT_API_KEY
make up                       # builds and starts postgres, redis, api, worker, web
make seed                     # loads the synthetic patients and users
```

Open **http://localhost:3000** and pick a demo user. The API is at http://localhost:8000/api/v1, with a health check at `/health`.

| Demo user | Role |
| --- | --- |
| Anjali Sharma | Caretaker (Asha, Suresh, Lakshmi) |
| Rohan Kumar | Caretaker (takes over Asha) |
| Meera Nair | Coordinator |

`make demo-reset` wipes the data and reseeds it (and recreates the memory banks).

> **Apple Silicon:** all images run natively. If Docker Desktop fails to start with *"Failed to install Rosetta"*, turn off *Settings → General → Use Rosetta for x86/amd64 emulation*.

## Run without Docker

Requires Python 3.12 with [uv](https://docs.astral.sh/uv/) and Node 20+. This uses SQLite, in-process events, the local memory backend and the rule-based agent, and needs no network access.

```bash
# terminal 1: API
cd apps/api && uv sync
DATABASE_URL=sqlite+aiosqlite:///./carebridge.db REDIS_URL= uv run python -m app.seed.load --reset
cd ../.. && make dev-api                      # PORT=8010 make dev-api if 8000 is busy

# terminal 2: web
cd apps/web && npm install
NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1 npm run dev
```

## Configuration

Settings are read from `.env` at the repo root (see [`.env.example`](.env.example)). `.env` is git-ignored, so never commit real keys.

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | `sqlite+aiosqlite:///./carebridge.db` | Database URL. Docker uses `postgresql+asyncpg://carebridge:carebridge@postgres:5432/carebridge`. |
| `REDIS_URL` | *(empty)* | Redis for events and cache. Leave empty to run in-process. |
| `GROQ_API_KEY` | *(empty)* | Enables the LLM agent. Leave empty to use the rule-based agent. |
| `GROQ_MODEL` / `GROQ_FALLBACK_MODEL` | `openai/gpt-oss-120b` / `qwen/qwen3-32b` | Primary and fallback models. |
| `HINDSIGHT_API_KEY` | *(empty)* | Enables Hindsight Cloud memory. Leave empty to use the local memory backend. |
| `HINDSIGHT_BASE_URL` | `https://api.hindsight.vectorize.io` | Hindsight API endpoint. |
| `JWT_SECRET` | `change-me` | Signs session tokens. **Set a random value.** |
| `ORG_SLUG` | `demo` | Prefix for memory bank IDs. |
| `CORS_ORIGINS` | `http://localhost:3000` | Allowed web origins. |
| `MEMORY_ENABLED` | `true` | Global memory switch (also togglable in the UI). |
| `APP_TZ` | `Asia/Kolkata` | Timezone for todos and check-ins. |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000/api/v1` | API URL used by the web app (build-time). |

The `/health` endpoint reports which backends are active, e.g. `{"memory_backend": "hindsight", "llm": "groq"}`.

## Demo walkthrough

A 3-minute story that exercises every workflow:

1. **Enroll** a patient in 5 large-format steps. This creates the memory bank, retains the first memory and queues verification with the coordinator.
2. **Anjali's board** shows 3 patients ordered with reasons (*"Serve lunch: gets anxious if lunch is late · observed 4×"*).
3. In chat: **"Was Asha's bath done?"** → *Not done* → *Refused* → *Feels cold*. CareBridge proposes **"Move to 1:30 PM?"** with cited events. Accept it.
4. **"Asha is restless after dinner"** → *Save*. CareBridge suggests a **10-minute assisted walk**, with 3 cited occurrences.
5. A **trend banner** flags 3 nights of short sleep, worded as *an observation, not a diagnosis*.
6. Switch to **Rohan**: **"I'm taking over Asha tonight"** returns a cited handoff briefing.
7. Click **Compare memory on/off** to see the same question answered without and with memory.

## Testing

```bash
make test                     # 22 API tests: auth scoping, safety guard, W3–W9 story, memory contract
make lint                     # ruff + ESLint
cd apps/web && npm run e2e    # Playwright: the full demo story + enrollment (offline stack)

# the same Playwright story against the Docker stack (Postgres + Redis, live Groq if a key is set)
cd apps/web && E2E_API_PORT=8000 \
  E2E_SEED_CMD="docker compose exec -T api python -m app.seed.load --reset" npx playwright test

cd apps/api && uv run pytest -m live   # optional: real Hindsight round-trip (needs HINDSIGHT_API_KEY)
```

CI runs on GitHub Actions (`.github/workflows/ci.yml`).

## Project structure

```
apps/
  api/                 FastAPI + SQLAlchemy 2 (async) + Alembic
    app/agent/         chat agent: LLM driver, rule driver, tools, handoff, quick-reply actions
    app/guard/         input/output safety checks
    app/memory/        the only package that talks to Hindsight (plus the local backend)
    app/learning/      failure-reason clustering → reschedule proposals (W7)
    app/trends/        rule-based trend alerts (W8)
    app/orchestrator/  board ordering and hints (W9)
    app/worker/        scheduled jobs: check-ins, retain retries, memory refresh, trend scan
    migrations/        Alembic migrations
    tests/             pytest suite
  web/                 Next.js 15 (App Router, TypeScript, TanStack Query, dnd-kit, SSE)
    app/               routes: dashboard, patients, coordinator, enroll
    components/        Board, ChatPanel, Shell, cards
    e2e/               Playwright tests
seed/                  synthetic people and patients (JSON)
docs/                  build plan and design decisions
architecture.md        product and technical spec
carebridge-ui.html     UI reference design
docker-compose.yml     full stack
```

## How CareBridge uses Hindsight

All memory access goes through `apps/api/app/memory/`, the only package that imports `hindsight_client`.

**One bank per patient.** The server derives `bank_id = cb-{ORG_SLUG}-patient-{patient_uuid}` from the authorized patient, never from the client. Each bank is created with:
- a mission;
- `disposition = {skepticism: 4, literalism: 4, empathy: 4}`;
- four **directives**: no diagnosis or dosing, no medical causes, cite dates and caretakers, and say so when evidence is thin;
- three **mental models**: `routine-and-timing`, `what-helps` and `handoff-essentials`.

**Retain facts that are attributed and timestamped.** PostgreSQL is written first, then the fact is retained:

```python
await memory.retain_fact(
    patient,
    text="On 6 Nov 2026 08:10, caretaker Anjali marked 'Morning bath' for Asha Rao NOT DONE. Reason: refused, feels cold.",
    occurred_at=at, context="todo_outcome", source_type="todo_event", source_id=event.id,
    metadata={"caretaker_name": "Anjali", "category": "hygiene", "status": "not_done"},
)   # → client.aretain(..., document_id="todo_event:<uuid>", timestamp=at, metadata=...)
```

Every retain writes a `memory_link` row. If a retain fails, the row is marked `failed` and the worker retries it later, so a failed retain never crashes a chat turn.

| Workflow | Hindsight use |
| --- | --- |
| W9 board reasons | Observations → cached hints, refreshed nightly |
| W7 reschedule | `recall` of failure reasons and success contexts → proposal with dated, attributed evidence |
| W6 what worked | `recall(types=["observation"])`, needing ≥2 supporting facts in 30 days |
| W5 handoff | `reflect` plus targeted recalls, rendered with (caretaker, date) citations |
| W8 trends | Deterministic rules on PostgreSQL; `recall` supplies the narrative evidence |

Repeated facts (e.g. "restless → assisted walk → calmed", three times) consolidate into **observations with a proof count**. They appear on the patient's *Memory* tab and as **"Memory used"** chips on every answer that used them.

## Safety

CareBridge **never diagnoses, prescribes, changes or estimates doses, or infers medical causes.**

- The agent has no tool or endpoint for creating or editing medications. Medication todos come only from *verified* medications.
- Self-reported data waits for coordinator verification.
- The output guard drops suggestions that have no supporting evidence.
- Urgent words (fall, chest pain, breathing difficulty, unresponsive, bleeding) trigger an emergency instruction and an escalation to the coordinator.
- Learned patterns are always labelled *"Observed pattern — not a clinical instruction."*
- Caretakers can only see patients they are assigned to. This is enforced server-side, and the tests cover the 403 checks.

## Further reading

- [`architecture.md`](architecture.md): full product and technical spec
- [`docs/DECISIONS.md`](docs/DECISIONS.md): design decisions and deviations from the spec
- [`docs/PLAN.md`](docs/PLAN.md): build plan
- [`carebridge-ui.html`](carebridge-ui.html): UI reference
