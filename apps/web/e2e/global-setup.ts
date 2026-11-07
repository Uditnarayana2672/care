import { execSync } from "node:child_process";
import path from "node:path";

/** Every run starts from the canonical seed so the demo story is reproducible. */
export default async function globalSetup() {
  const db = process.env.E2E_DATABASE_URL || "sqlite+aiosqlite:///./carebridge.db";
  execSync("uv run python -m app.seed.load --reset", {
    cwd: path.resolve(__dirname, "../../api"),
    env: { ...process.env, DATABASE_URL: db, REDIS_URL: "" },
    stdio: "inherit",
  });
}
