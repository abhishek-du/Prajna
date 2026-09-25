# Prajna web client

A market-data research interface over the Prajna read API (`backend/app/readapi`, `/v1`). It is read-only. It never fabricates values, never presents stored data as live, and contains no Stage 3 functionality (Stage 3 is locked).

```bash
# backend (read-only API, localhost)
cd backend && .venv/bin/python -m app.readapi --host 127.0.0.1 --port 8090
# frontend
cd web && npm install
npm run dev          # http://localhost:5173 (proxies /v1 to 127.0.0.1:8090; override with PRAJNA_API_URL)
npm run build        # dist/
npm test             # vitest
npm run e2e          # Playwright (needs the API and `npx vite preview --port 4173`)
```

Documentation: `docs/web/`, which contains `FRONTEND_ARCHITECTURE.md`, `FRONTEND_ROUTES.md`, `FRONTEND_API_MAPPING.md`, `FRONTEND_COMPONENTS.md` and `FRONTEND_TESTING.md`. The API contract is `docs/API_CONTRACT.md`.

Two constraints on data:
- **Test fixtures** live only in `mocks/`. They are imported only by tests, and this is enforced by `src/app.boundaries.test.ts`.
- **No credentials.** The client holds none: the API exposes none and the client only issues `GET`s.
