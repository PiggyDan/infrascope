# Day 2 Progress — InfraScope

_Last updated: 2026-10-21_

## Part 1 — Authentication & authorization ✅

| Item | Status | Evidence |
|---|---|---|
| API keys (`X-API-Key`), SHA-256 hashed, shown once | ✅ | `test_auth.py`; DB row check: hash only |
| Roles: VIEWER read-only, ADMIN write + key mgmt | ✅ | tests; live: VIEWER `POST /targets` → 403 |
| Every non-public route requires a key | ✅ | route-walking test; **mutation check**: removing auth from incidents router → test fails |
| Revoked / expired / malformed keys rejected | ✅ | tests |
| Last ADMIN key can't be revoked via API | ✅ | test (409) |
| CLI `create-api-key` / `list-api-keys` / `revoke-api-key` | ✅ | test + used live |
| Rejected keys never logged | ✅ | caplog test |
| Migration 0002 on existing PostgreSQL data | ✅ | `Running upgrade 0001 -> 0002` in api logs; drift test passes |
| Live smoke test with auth | ✅ | `smoke-test.ps1` PASSED (incident opened/resolved) |
| Tests | ✅ | **141 passed** in container on PostgreSQL; 136 + 5 skipped locally (SQLite) |

Live state after verification: both temporary keys used for testing (`smoke-test-temp`,
`viewer-temp`) are **revoked**. No active keys exist; the owner creates their own ADMIN key.

### Files (Part 1)
- New: `app/api/auth.py`, `app/api/api_keys.py`, `app/services/api_keys.py`, `app/cli.py`,
  `migrations/versions/20261021_0002_api_keys.py`, `tests/test_auth.py`, this file
- Changed: `app/models.py`, `app/schemas.py`, `app/main.py`, `app/api/{targets,incidents,summary}.py`,
  `tests/conftest.py`, `tests/test_persistence.py`, `tests/test_monitor_engine.py`,
  `tests/integration/test_test_target.py`, `scripts/smoke-test.ps1`, README, API, ARCHITECTURE

## Part 2 — Dashboard ✅

| Item | Status | Evidence |
|---|---|---|
| React + TS dashboard (Vite), pinned deps | ✅ | `npm audit --omit=dev`: 0 vulnerabilities |
| Sign-in with API key; 401 → signed out | ✅ | seen live (an unset key fell back to sign-in) |
| Summary tiles, targets table, incidents, target detail | ✅ | screenshots `docs/images/` |
| ADMIN: add / pause / delete (inline confirm); VIEWER read-only | ✅ | UI hides writes; API enforces 403 |
| Response-time chart: crosshair tooltip, keyboard, failure markers, end label, legend | ✅ | tooltip verified in headless Edge |
| Palette validated (CVD/contrast) light + dark | ✅ | `validate_palette.js`: all checks pass both modes |
| nginx container, same-origin `/api` proxy, strict CSP + security headers | ✅ | curl header check; no CSP violations in browser console |
| `web` cannot reach `db` | ✅ | `wget db:5432` → bad address |
| Light, dark, 400px phone rendering | ✅ | screenshots checked by eye; no page-level horizontal overflow |
| Frontend tests | ✅ | **49 passed** (Vitest); `tsc` strict clean |

Visual issues found from screenshots and fixed: check rows said "Down" (now "OK"/"Failed"),
incident rows wrapped, "0.0%" uptime, clipped Delete column, redundant "HTTP 503" text,
cramped phone URLs.

Demo data left in the dev database: targets `demo-healthy`, `demo-slow`, `demo-unhealthy`
(the last keeps an open incident on purpose, to show a failure). Pause or delete them from
the dashboard.

### Files (Part 2)
- New: `frontend/` (package.json + lockfile, tsconfig, vite config, nginx.conf,
  security-headers.conf, Dockerfile, `src/**`), `docs/images/dashboard-{light,dark}.png`
- Changed: `compose.yaml` (web service), `.env.example` (`WEB_PORT`), `.gitignore`, README,
  ARCHITECTURE

## Known problems / notes
- No rate limiting on failed auth (256-bit keys make guessing infeasible; still worth adding
  before any non-localhost exposure).
- Plain HTTP; TLS needed before exposing beyond localhost.
- Native PostgreSQL 13 on `0.0.0.0:5432` (outside this project, see Day 1 notes).

## Live state at end of Day 2
- Stack: `api`, `db`, `testtarget`, `web` all healthy; dashboard at http://127.0.0.1:3000.
- API keys: all 5 temporary keys created for verification are **revoked**; 0 active. The
  owner creates their own with the CLI.

## Next task (Day 3)
1. GitHub Actions CI: ruff + pytest (with a PostgreSQL service) + frontend tsc/vitest/build.
2. README polish for reviewers: CI badge, "what I'd do next" section.
3. Optional: rate limiting on failed auth; results retention.
