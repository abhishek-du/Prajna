# Prajna Baseline Audit Evidence

**Date / Timestamp:** 2026-09-28T18:41:00+05:30  
**Auditor:** Independent Auditor & Verification Engineer  
**Repository Path:** `/home/cis/windows/prajna`

---

## 1. Git Status & Working Tree

### Command
```bash
git status
```

### Output
```text
On branch main
Changes not staged for commit:
  (use "git add <file>..." to update what will be committed)
  (use "git restore <file>..." to discard changes in working directory)
	modified:   backend/ops/cron/prajna.cron

Untracked files:
  (use "git add <file>..." to include in what will be committed)
	backend/app/api/
	backend/app/features/audit_doc.py
	backend/ops/measure/stage3_timing.py
	backend/ops/runbooks/stage3_snapshot.sh
	backend/tests/unit/test_api_endpoints.py
	docs/API_INVENTORY.md
	docs/FRONTEND_ARCHITECTURE.md
	docs/STAGE_1_TIMING_AND_FINAL_ACCEPTANCE_REPORT.md
	docs/STAGE_3_READINESS_REPORT.md
	docs/WEBSOCKET_LIVE_CONTRACT.md
	frontend/

no changes added to commit (use "git add" and/or "git commit -a")
```

### Assessment
- **Current Branch:** `main`
- **Working Tree Clean:** `NO` (1 tracked modified file: `backend/ops/cron/prajna.cron`, 10 untracked files/directories)
- **Uncommitted Modifications:**
  - `backend/ops/cron/prajna.cron`: Added commented-out Stage 3 snapshot schedules marked `# PENDING_APPROVAL: ...` (not active).

---

## 2. HEAD Commit & Recent Commits

### Command
```bash
git rev-parse HEAD
git log -n 15 --oneline
```

### Output
```text
0fa483948404c32b78523df885acbf1fe7fbcd61
0fa4839 (HEAD -> main) stage3: add adversarial PIT coverage
c42cb0d stage3: use repeatable read snapshot
580f587 stage3: enforce fii-dii staleness (decision FII-DII-STALENESS, approved)
1ee5e54 docs: news status - migration 0014 applied to production (backup verified), API live and empty while locked
45cb3ac news: per-source acceptance gate, human mapping review, restart-safe politeness, status report
0df42c5 readapi: multi-source news endpoints (read only, point in time, facts apart from derived/AI)
bba29b0 news: proposed point-in-time news features (dry-run only, decision FEATURE-NEWS-V2 pending)
0c38fe0 news: Stage 2 point-in-time layer for multi-source news, and persistence of all layers
14725c2 news: content retrieval, versioned AI enrichment, latency and health reporting
1ef70a9 news: migration 0014 - normalisation fields, stories, mentions, assessments, content, AI
71fe47a news: entity mentions, reviewed aliases, story grouping and rule-based assessment
7dbaece news: one write flag per source, and write locks gated on acceptance and Stage 2
e84fbb9 docs: news subsystem inventory (phase 1, no code change)
c557e68 stage1: header comment states the COMPLETE rule the code applies
28fa3cb stage1: COMPLETE - final acceptance regenerated (2026-09-28)
```

---

## 3. Stage 1 & Stage 3 Implementation Commits Identified

### Stage 1 Key Commits
- `28fa3cb`: `stage1: COMPLETE - final acceptance regenerated (2026-09-28)`
- `ab69528`: `stage1: criterion X is decided by B1 and the revised B2 only`
- `c557e68`: `stage1: header comment states the COMPLETE rule the code applies`

### Stage 3 Implementation Commits
- `c36d81e`: `stage3: feature registry and pure feature computations`
- `b4972f8`: `stage3: feature storage, engine and execution locks`
- `c54816d`: `stage3: CLI and read API surfaces (stored values only)`
- `4d34c1b`: `stage3: acceptance gate with readiness levels, and the design document`
- `4e8c822`: `stage3: record the user's approval of FEATURE-PARAMS`
- `8b612e0`: `stage3: ready-for-unlock review (not yet ready: Stage 1 X pending)`
- `580f587`: `stage3: enforce fii-dii staleness (decision FII-DII-STALENESS, approved)`
- `c42cb0d`: `stage3: use repeatable read snapshot`
- `0fa4839`: `stage3: add adversarial PIT coverage` (HEAD)

---

## 4. Python Environment & Tooling

### Commands & Results
- Python Binary: `/home/cis/windows/prajna/backend/.venv/bin/python`
- Python Version: `Python 3.11.16` (uv managed cpython-3.11-linux-x86_64-gnu)
- CLI Entrypoint: `/home/cis/windows/prajna/backend/.venv/bin/prajna`
- Test Runner: `/home/cis/windows/prajna/backend/.venv/bin/pytest`
- Migration Tool: `/home/cis/windows/prajna/backend/.venv/bin/alembic`

---

## 5. Database Configuration & State

### Environment Inspection (Credentials Redacted)
- Configuration file: `backend/.env`
- Production Database URL: `postgresql+asyncpg://prajna_rw:***@localhost:5432/prajna`
- Test Database URL: `postgresql+asyncpg://prajna_rw:***@localhost:5432/prajna_test`
- Production DB Connected: `YES` (database: `prajna`, user: `prajna_rw`)
- Production DB Alembic Revision: `0014`
- Test DB Connected: `YES` (database: `prajna_test`, user: `prajna_rw`)
- Test DB Alembic Revision: `0014`

### Production Flags in `.env`
- `PRAJNA_STAGE3_ENABLED`: Not defined in `.env` (defaults to `false` in code)
- `PRAJNA_STAGE3_BACKFILL_ENABLED`: Not defined in `.env` (defaults to `false` in code)
- `PRAJNA_NEWS_MULTI_SOURCE_ENABLED`: Not defined in `.env` (defaults to `false` in code)
- `PRAJNA_WRITE_TOKEN`: Configured in `.env` (redacted, required for manual CLI writes)

### Locks and Crons
- `backend/var/run/stage3.kill`: NOT present (Kill switch inactive)
- System Crontab (`crontab -l`): Contains Stage 1 and Stage 2 maintenance jobs. Stage 3 is NOT present in system crontab.
- Systemd: No prajna services/timers installed.
