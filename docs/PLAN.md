# CareBridge build plan

- [x] **Phase 1 — Foundation:** monorepo, `docker-compose.yml`, Dockerfiles (api / worker / web), `.env.example`, Makefile, CI (ruff + pytest, eslint + build)
- [x] **Phase 2 — Data model & auth:** all §5 entities + Alembic migration `0001`; demo-login JWT cookie; `get_current_user`, `require_role`, `require_assignment`; 403 tests
- [x] **Phase 3 — Memory service:** `app/memory/service.py` (`ensure_bank`, `retain_fact`, `recall`, `reflect`, `refresh_mental_models`); Hindsight backend + offline local backend; `MEMORY_ENABLED` toggle; fake-client contract tests; opt-in `pytest -m live`
- [x] **Phase 4 — Enrollment (W1):** `POST /enrollments`, 5-step large-text wizard with review + success + autosave; coordinator verification queue
- [x] **Phase 5 — Todos, Kanban, orchestration (W2, W9):** generate, deterministic score + reasons, hints cache, `/me/board`, dnd-kit board, worker jobs (05:30 IST + lazy)
- [x] **Phase 6 — Chat agent (W3, W4, W5):** SSE events, tool registry with Pydantic args, Groq loop + deterministic fallback driver, guard, check-ins (SSE push + `/me/checkins`)
- [x] **Phase 7 — Learning (W6, W7, W8):** `what_worked`, `failures`, `trends/watch`
- [x] **Phase 8 — Patient profile & memory view:** Today / Timeline / Memory / Alerts tabs; memory on/off compare
- [x] **Phase 9 — Seed & demo:** `seed/*.json` + `app.seed.load` (14 days, replayed with original timestamps via `retain_batch`); `make demo-reset`
- [x] **Phase 10 — Quality & docs:** pytest (22 tests), Playwright demo story, README, DECISIONS

Not verified in this environment (no Docker / Hindsight key / Groq key available): `docker compose up`, live Hindsight Cloud, live Groq. See `docs/DECISIONS.md`.
