# CareBridge

A chat-first care assistant for home caretakers of elderly patients. **Hindsight** (by Vectorize) is the persistent memory layer: every todo outcome and care log becomes an attributed, timestamped fact, and the agent gets measurably better at caring for each patient — and any caretaker can pick up where the last one left off.

> Synthetic data only. The team coordinated build agents with **Band AI desktop**.

- Spec: [`architecture.md`](architecture.md) · UI reference: [`carebridge-ui.html`](carebridge-ui.html) · Decisions: [`docs/DECISIONS.md`](docs/DECISIONS.md) · Plan: [`docs/PLAN.md`](docs/PLAN.md)

```
apps/web   Next.js 15 (App Router, TS, TanStack Query, dnd-kit, SSE)
apps/api   FastAPI + SQLAlchemy 2 async + Alembic + APScheduler worker
seed       synthetic people / patients (JSON) — loader in apps/api/app/seed
infra, docs
```

## Run it

**Docker (Postgres 16, Redis 7, api, worker, web):**
```bash
cp .env.example .env     # add HINDSIGHT_API_KEY / GROQ_API_KEY for the real thing
make up && make seed     # web :3000, api :8000
```

**No Docker (SQLite, in-process events, local memory backend, rule agent — works offline):**
```bash
cd apps/api && uv sync
make dev-api             # terminal 1 (PORT=8010 make dev-api if 8000 is busy)
cd apps/api && DATABASE_URL=sqlite+aiosqlite:///./carebridge.db REDIS_URL= uv run python -m app.seed.load --reset
cd apps/web && npm install && NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1 npm run dev   # terminal 2
```
Open http://localhost:3000 and pick a demo user (Anjali / Rohan caretakers, Meera coordinator).

```bash
make test        # 22 API tests (auth scoping, safety, W3–W9 story, memory contract)
cd apps/web && npm run e2e   # Playwright: full 3-minute demo story + enrollment
# same story against the docker stack (Postgres + Redis):
cd apps/web && E2E_API_PORT=8000 E2E_SEED_CMD="docker compose exec -T api python -m app.seed.load --reset" npx playwright test
cd apps/api && uv run pytest -m live   # optional: real Hindsight Cloud round-trip (needs HINDSIGHT_API_KEY)
make demo-reset  # wipe + reseed (and delete/recreate memory banks)
```

## How CareBridge uses Hindsight

All memory access goes through `apps/api/app/memory/` — the only package that imports `hindsight_client`.

**One bank per patient.** `bank_id = cb-{ORG_SLUG}-patient-{patient_uuid}`, derived server-side from the authorized patient (never from the client). `ensure_bank` creates it with the mission, `disposition = {skepticism: 4, literalism: 4, empathy: 4}`, four **directives** (no diagnosis/dosing, no medical causes, observations with dates and caretakers, say so when evidence is thin) and three **mental models** (`routine-and-timing`, `what-helps`, `handoff-essentials`).

**Retain: factual, attributed, timestamped.** PostgreSQL is written first, then:
```python
await memory.retain_fact(
    patient,
    text="On 6 Nov 2026 08:10, caretaker Anjali marked 'Morning bath' for Asha Rao NOT DONE. Reason: refused, feels cold.",
    occurred_at=at, context="todo_outcome", source_type="todo_event", source_id=event.id,
    metadata={"caretaker_name": "Anjali", "category": "hygiene", "status": "not_done", ...},
)   # → client.aretain(..., document_id="todo_event:<uuid>", timestamp=at, metadata=...)
```
Every retain writes a `memory_link` row; failures are marked `failed` and retried by the worker, never crashing a chat turn.

**Recall / reflect / observations**
| Workflow | Hindsight use |
| --- | --- |
| W9 board reasons | observations → cached hints ("Patel anxious if lunch is late, observed 4×"), refreshed nightly |
| W7 reschedule | `recall` failure reasons + success contexts → proposal with dated, attributed evidence |
| W6 what worked | `recall(types=["observation"])` with ≥2 supporting facts in 30 days |
| W5 handoff | `reflect` + targeted recalls, rendered with (caretaker, date) citations |
| W8 trends | deterministic rules on PostgreSQL; `recall` supplies narrative evidence; alert raise/ack retained |
Repeated facts ("restless → assisted walk → calmed" ×3) consolidate into **observations with a proof count**; the UI shows them on the patient *Memory* tab and as "Memory used" chips on every answer that used them.

**Before/after.** The chat panel's *Memory* switch (`MEMORY_ENABLED` at runtime) and *Compare memory on/off* button answer the same handoff question without and with memory.

## Safety statement

CareBridge **never diagnoses, prescribes, changes or estimates doses, or infers medical causes.** There is no tool or endpoint through which the agent creates or edits medications; medication todos come only from *verified* medications; pending self-reported data waits for a coordinator. Suggestions without evidence are dropped by the guard; urgent words (fall, chest pain, breathing, unresponsive, bleeding) trigger an emergency instruction and an escalation. Learned patterns are always labelled *"Observed pattern — not a clinical instruction."*

## Demo script (3 minutes)
1. **Enroll** a patient in 5 big screens → bank created, first memory retained, coordinator verification queued.
2. **Anjali's board**: 3 patients ordered with reasons (*"Serve lunch — gets anxious if lunch is late · observed 4×"*).
3. Chat **"Was Asha's bath done?"** → Not done → Refused → *Feels cold* → W7 proposal **"Move to 1:30 PM?"** with 4 cited events → accept.
4. **"Asha is restless after dinner"** → Save → W6 **"10-minute assisted walk"** with 3 cited occurrences.
5. Trend banner: short sleep 3 nights (W8) — *"an observation, not a diagnosis"*.
6. Switch to **Rohan**: *"I'm taking over Asha tonight"* → cited handoff briefing (W5).
7. **Compare memory on/off** for the before/after.
