import { defineConfig } from "@playwright/test";

// E2E against the real read API through the production preview:
//   backend: .venv/bin/python -m app.readapi --port 8090   (read-only)
//   web:     npx vite preview --port 4173                  (proxies /v1)
// Uses the system Google Chrome (channel "chrome").
export default defineConfig({
  testDir: "./e2e",
  timeout: 45_000,
  expect: { timeout: 15_000 },
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: process.env.PRAJNA_WEB_URL ?? "http://127.0.0.1:4173",
    channel: "chrome",
    headless: true,
    screenshot: "only-on-failure",
  },
});
