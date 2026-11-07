import { defineConfig } from "@playwright/test";

const API_PORT = process.env.E2E_API_PORT || "8010";
export default defineConfig({
  testDir: "./e2e",
  globalSetup: "./e2e/global-setup.ts",
  timeout: 90_000,
  workers: 1,
  use: { baseURL: process.env.E2E_BASE_URL || "http://localhost:3000", viewport: { width: 1440, height: 900 } },
  webServer: [
    {
      // seeds a fresh SQLite db, then serves the API (local memory backend + rule agent: fully offline)
      command: `sh -c "cd ../api && DATABASE_URL=sqlite+aiosqlite:///./carebridge.db REDIS_URL= uv run python -m app.seed.load --reset && DATABASE_URL=sqlite+aiosqlite:///./carebridge.db REDIS_URL= CORS_ORIGINS=http://localhost:3000 uv run uvicorn app.main:app --port ${API_PORT}"`,
      url: `http://localhost:${API_PORT}/api/v1/health`,
      reuseExistingServer: true,
      timeout: 60_000,
    },
    {
      command: `sh -c "NEXT_PUBLIC_API_URL=http://localhost:${API_PORT}/api/v1 npm run dev"`,
      url: "http://localhost:3000",
      reuseExistingServer: true,
      timeout: 120_000,
    },
  ],
});
