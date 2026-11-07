# CareBridge — End-to-End Build Prompt for Claude Code

> Put `architecture.md` and `carebridge-ui.html` in the repo root, open Claude Code there, and paste everything below the line.

---

You are a senior full-stack engineer building **CareBridge** end to end in this repository, in one continuous session. CareBridge is a chat-first care assistant for home caretakers of elderly patients, with **Hindsight** (by Vectorize) as the persistent memory layer. The product must clearly show memory making the agent better over time.

## 0. Read first (mandatory)

1. Read `architecture.md` fully. It is the source of truth for scope, data model, workflows W1–W9, API routes, safety rules, and the demo story. Do not drop any workflow.
2. Open `carebridge-ui.html`. It is the **visual and interaction reference**: layout, colors, component shapes, copy, and states. Port its design into real components — do not ship the HTML file itself.
3. Before writing any Hindsight code, verify the current Python client API at https://hindsight.vectorize.io/sdks/python and https://hindsight.vectorize.io/developer/api/quickstart (package `hindsight-client`, class `Hindsight`, methods `create_bank`, `retain`, `retain_batch`, `recall`, `reflect`, `list_memories`, mental-model and directive helpers, async `a*` variants). If anything in this prompt disagrees with the docs, follow the docs and note it in `docs/DECISIONS.md`.

Then create `docs/PLAN.md` with your phase checklist and keep it updated as you go.

## 1. Stack (do not substitute)

| Layer | Choice |
| --- | --- |
| Monorepo | `apps/web`, `apps/api`, `infra`, `seed`, `docs` |
| Web | Next.js 15 App Router, TypeScript, Tailwind, shadcn/ui, TanStack Query, `@dnd-kit` for Kanban, EventSource for SSE |
| API | Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 (async), Alembic, `uv` for deps |
| DB | PostgreSQL 16 |
| Queue / pubsub | Redis 7 + APScheduler (in a separate `worker` process) |
| Memory | Hindsight Cloud via `hindsight-client` (async methods) |
| LLM | Groq via the OpenAI-compatible client, model `openai/gpt-oss-120b` (fallback `qwen/qwen3-32b`), with function calling |
| Auth | Demo-login (pick a seeded user) issuing a signed JWT cookie; RBAC roles `caretaker`, `coordinator`, `admin` |
| Tests | pytest + httpx for API, Playwright for one end-to-end demo test |
| Local run | `docker compose up` brings up postgres, redis, api, worker, web |

Environment (`.env.example`):

```
DATABASE_URL=postgresql+asyncpg://carebridge:carebridge@postgres:5432/carebridge
REDIS_URL=redis://redis:6379/0
HINDSIGHT_BASE_URL=https://api.hindsight.vectorize.io   # confirm exact URL in docs / Cloud UI
HINDSIGHT_API_KEY=
GROQ_API_KEY=
GROQ_MODEL=openai/gpt-oss-120b
JWT_SECRET=change-me
ORG_SLUG=demo
NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1
MEMORY_ENABLED=true
```

## 2. Non-negotiable rules

1. **Safety boundary.** The app never diagnoses, prescribes, estimates or changes doses, or infers medical causes. There is **no tool or endpoint** through which the agent creates or edits medications. Medication todos come only from medications with `verification = verified`.
2. **Two sources of truth.** PostgreSQL is authoritative. Hindsight holds learned context. Write PostgreSQL first, then retain.
3. **One Hindsight bank per patient**, ID `cb-{ORG_SLUG}-patient-{uuid}`, derived server-side from the authorized patient. Never accept bank IDs from the client. Only `apps/api/app/memory/` may import `hindsight_client`.
4. **Every retain is a factual, attributed, timestamped sentence** (who, when, what, outcome, reason) with `timestamp`, `context`, `document_id = "<source_type>:<source_id>"`, and `metadata` (source_type, source_id, caretaker_id, category). Store a `memory_link` row for every retain.
5. **Every suggestion shown in the UI has evidence** (date + caretaker + text). Uncited suggestions are dropped by the guard.
6. **Assignment scoping** on every patient route via a `require_assignment` dependency.
7. **Synthetic data only.**
8. Retain/recall failures must never crash a chat turn: log, mark `memory_link.status = failed`, retry in the worker, and tell the user only if the action itself failed.
9. LLM tool calls can be malformed (this model sometimes emits bad JSON). Validate every tool call with Pydantic; on failure, send the validation error back as the tool result once, then fall back to a plain reply.

## 3. Build phases

Work through these in order. After each phase run tests and lint, fix failures, tick the box in `docs/PLAN.md`, and commit with a clear message.

### Phase 1 — Foundation
- Monorepo scaffold, `docker-compose.yml`, Dockerfiles for api/worker/web, `.env.example`, Makefile (`make up`, `make seed`, `make test`, `make demo-reset`).
- Ruff + mypy for Python, ESLint + Prettier for web, GitHub Actions CI running lint + tests.
- **Done when:** `docker compose up` serves a health endpoint and a blank Next.js page.

### Phase 2 — Data model & auth
- SQLAlchemy models + Alembic migration for every entity in `architecture.md` §5 (plus `assignment`, `patient_contact`, `condition`, `chat_message`, `audit_event`).
- Demo login: `/auth/demo-login` with user picker; JWT cookie; `get_current_user`, `require_role`, `require_assignment`.
- **Done when:** a caretaker can only read assigned patients (pytest proves 403 otherwise).

### Phase 3 — Memory service (Hindsight adapter)
Create `apps/api/app/memory/service.py` with an async `MemoryService` wrapping the client:

```python
class MemoryService:
    async def ensure_bank(self, patient: Patient) -> str: ...       # create_bank with mission, disposition, directives
    async def retain_fact(self, patient: Patient, *, text: str, occurred_at: datetime,
                          context: str, source_type: str, source_id: UUID,
                          metadata: dict) -> MemoryLink: ...
    async def recall(self, patient: Patient, query: str, *, types: list[str] | None = None,
                     max_tokens: int = 2048, budget: str = "mid") -> list[MemoryItem]: ...
    async def reflect(self, patient: Patient, question: str, *, context: str | None = None,
                      budget: str = "mid") -> ReflectAnswer: ...       # answer + cited memory ids
    async def refresh_mental_models(self, patient: Patient) -> None: ...  # routine-and-timing, what-helps, handoff-essentials
```

- Bank mission, disposition, and directives exactly as `architecture.md` §6.1. Use the docs to find how directives and mental models are created; if directives are not settable via the client helper, use the generated `client.directives` namespace.
- `MemoryItem` exposes `id`, `text`, `type`, `occurred_at`, `caretaker_name`, `source_type`, `source_id` (from metadata / document id) so the UI can render evidence cards.
- `MEMORY_ENABLED=false` makes recall/reflect return empty — used for the before/after demo toggle.
- Contract tests against a fake client; one opt-in live test (`pytest -m live`) against Hindsight Cloud.
- **Done when:** a script retains three facts for a test patient and recalls them with attribution.

### Phase 4 — Enrollment (W1)
- `POST /enrollments`: patient, contacts, conditions, routines; medications + allergies with `verification=pending` unless created by staff; `ensure_bank`; retain an enrollment summary; coordinator alert "verify medical data".
- Web `/enroll`: 5-step wizard matching the HTML reference (18px+ base text, 56px touch targets, chips over free text, autosave to localStorage, progress bar, back/next, review screen, success screen with patient code). Must be usable by an elderly person on a phone.
- Coordinator `/coordinator` verification queue (verify / reject meds and allergies).

### Phase 5 — Todos, Kanban, orchestration (W2, W9)
- `orchestrator/generate.py`: build today's todos from verified meds, routines, care-plan items, accepted suggestions; apply `routine-and-timing` hints (time windows only, never adds meds).
- `orchestrator/score.py`: deterministic score and human-readable `priority_reason` exactly as `architecture.md` W9; memory hints cached in Redis per patient, refreshed nightly by the worker.
- `GET /me/board` returns columns Now / Next / Later / Done / Not done with cards (patient, time, category, reason, memory chip).
- Web `/dashboard`: Kanban with patient filter chips, drag to change status (dragging to Not done opens the reason picker), alert banners, "Ask CareBridge" chat side panel.
- Worker job at 05:30 local (`Asia/Kolkata`) + lazy generation on first board load of the day.

### Phase 6 — Chat agent (W3, W4, W5)
- `POST /chat` streams SSE events: `token`, `card`, `quick_replies`, `memory_used`, `board_changed`, `done`.
- Tool registry exactly as `architecture.md` §7.2 with Pydantic arg models; patient IDs validated against the caller's assignments.
- System prompt from §7.3. Per turn: load assignments + today's todos, recall memory for the active patient, then tool loop (max 6 calls).
- **W3 check-in:** the worker publishes due-check-ins (due + 30 min, not done) to Redis; the web shows them as agent messages with buttons Completed / Not done / Skipped → reason buttons (Refused, Asleep, Unwell, No time, Other). Kanban drag and chat must call the same service function.
- **W4 logging:** free text → extraction into multiple `log_care` calls → a confirmation card listing entries [Save all] [Edit] → write + retain. Matching medication todo auto-marks done when a "given" med log is saved.
- **W5 handoff:** "taking over" / "what should I know" intents → `reflect` with `handoff-essentials` + open todos + open alerts + verified meds; answer cites (date, caretaker) per item; if insufficient, says so.
- `guard.py`: regex + LLM-check for dose/diagnosis language and uncited suggestions; urgent-sign keywords (fall, chest pain, breathing, unresponsive, bleeding) → emergency instruction + escalation.

### Phase 7 — Learning workflows (W6, W7, W8)
- **W6** `learning/what_worked.py`: triggered on watch-severity mood/sleep/diet logs or explicit question; recall observations; show only those with ≥2 supporting facts in 30 days and no care-plan conflict; card with evidence + [Try it] [Not now]; outcome retained.
- **W7** `learning/failures.py`: after each not_done/skipped, if ≥2 failures of the same template in 7 days, recall reasons + success contexts, create a reschedule `suggestion` with evidence; never for medication todos (suggest coordinator instead); accepting updates the template and retains the decision.
- **W8** `trends/watch.py`: deterministic rules from §8 W8 on PostgreSQL logs vs the patient's 14-day baseline; recall narrative evidence; create alert with "This is an observation, not a diagnosis…" line; dashboard banner + coordinator queue; retain alert raised/acknowledged.

### Phase 8 — Patient profile & memory view
- `/patients/[id]`: header (name, age, language, mobility, allergies with verification badges), tabs **Today**, **Timeline**, **Memory**, **Alerts**.
- Memory tab: observations (with proof count and evidence list) and recent facts, filter by category, each linking to its source log.
- Demo toggle on the chat panel: "Memory on/off" calls `/demo/memory-toggle` to answer the same question both ways side by side.

### Phase 9 — Seed & demo
- `seed/` JSON + `make seed` loader that writes PostgreSQL **and** replays historical events into Hindsight with the original timestamps (use `retain_batch`), so observations exist before the demo.
- Patients (all synthetic): Mrs. Asha Rao 78 (Telugu, walker, diabetic diet, evening restlessness, cold-morning bath refusals, recent short sleep), Mr. Suresh Patel 85 (mild memory issues, anxious if lunch is late), Mr. Imran Khan 82 (fall risk, walker), Mrs. Lakshmi Iyer 80 (reduced dinner intake trend).
- Caretakers: Anjali Sharma (assigned Asha, Suresh, Lakshmi), Rohan Kumar (takes over Asha tonight). Coordinator: Meera Nair.
- Cover 14 days of history ending yesterday so that the demo in `architecture.md` §12 works step by step: W9 reason for Patel's lunch, W7 bath proposal, W6 evening-walk pattern (3 occurrences), W8 sleep alert for Asha, W5 handoff for Rohan.
- `make demo-reset` wipes and reseeds (including deleting/recreating demo banks).

### Phase 10 — Quality & docs
- Loading, empty, error, and offline-draft states everywhere; mobile layouts for enrollment and chat.
- Tests: every item in `architecture.md` §13, plus a Playwright run of the full demo story.
- `README.md`: what it is, architecture diagram (link `architecture.md`), **"How CareBridge uses Hindsight"** section (banks, retain format, recall/reflect usage, observations, mental models, with code excerpts), setup, demo script, safety statement. Mention that the team coordinated build agents with Band AI desktop.
- `docs/DECISIONS.md`: any deviations and why.

## 4. Code conventions

- API layout: `apps/api/app/{core,auth,models,schemas,routers,services,memory,agent,guard,orchestrator,learning,trends,worker}`.
- Services hold logic; routers stay thin. One function per state change (e.g. `todos.service.set_status`) used by REST, chat tools, and tests.
- All datetimes timezone-aware; display in `Asia/Kolkata`.
- Web: server components for pages, client components for Kanban/chat; shared API types generated from FastAPI OpenAPI (`openapi-typescript`) into `apps/web/lib/api-types.ts`.
- No secrets in code. No `print` debugging left behind.

## 5. Definition of done

- `make up && make seed` then the demo in `architecture.md` §12 runs end to end in the browser without manual DB edits.
- All tests pass in CI.
- Every agent answer that uses memory shows a "Memory used" chip with evidence.
- Hindsight Cloud UI shows one bank per seeded patient with retained facts and consolidated observations.

When something is ambiguous, pick the option that keeps memory central and safety intact, record it in `docs/DECISIONS.md`, and keep going. Don't stop to ask unless a decision is irreversible.
