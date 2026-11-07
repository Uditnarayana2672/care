import { execSync } from "node:child_process";
import path from "node:path";

/**
 * Every run starts from the canonical seed so the demo story is reproducible.
 * Default reseeds the local SQLite db; against the docker stack set
 *   E2E_SEED_CMD="docker compose exec -T api python -m app.seed.load --reset" E2E_API_PORT=8000
 */
export default async function globalSetup() {
  const root = path.resolve(__dirname, "../../..");
  if (process.env.E2E_SEED_CMD) {
    execSync(process.env.E2E_SEED_CMD, { cwd: root, stdio: "inherit" });
    return;
  }
  const db = process.env.E2E_DATABASE_URL || "sqlite+aiosqlite:///./carebridge.db";
  execSync("uv run python -m app.seed.load --reset", {
    cwd: path.resolve(__dirname, "../../api"),
    env: { ...process.env, DATABASE_URL: db, REDIS_URL: "" },
    stdio: "inherit",
  });
}
