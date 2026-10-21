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

## Part 2 — Dashboard
_Not started._

## Known problems / notes
- No rate limiting on failed auth (256-bit keys make guessing infeasible; still worth adding
  before any non-localhost exposure).
- Plain HTTP; TLS needed before exposing beyond localhost.
- Native PostgreSQL 13 on `0.0.0.0:5432` (outside this project, see Day 1 notes).

## Next task
Part 2: React + TypeScript dashboard (Vite), served by an nginx container on 127.0.0.1 that
proxies `/api` to the backend (same origin, no CORS).
