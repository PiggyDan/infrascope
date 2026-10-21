# Day 1 Progress — InfraScope

_Last updated: 2026-10-21. **Day 1 complete.** All acceptance criteria verified on Docker + PostgreSQL._

## Environment
- Windows 11 workstation; project created from scratch on Day 1.
- Python 3.12 via `py -3.12` (system `python` is 3.8). The project venv `.venv` uses 3.12.
- Docker Desktop 4.96.0 (Engine 29.9.1) installed via `winget` on Day 1, WSL 2 backend.
- `.env` created from `.env.example` with a randomly generated 32-char `POSTGRES_PASSWORD`
  (never printed; git-ignored).

## Acceptance criteria

| Criterion | Status | Evidence |
|---|---|---|
| Docker Compose starts successfully | ✅ | `docker compose up -d --build`; all 3 services `healthy` |
| FastAPI health endpoint responds | ✅ | `/health` → `status=ok database=ok monitor=running` |
| PostgreSQL connects successfully | ✅ | health `database=ok`; tests ran with dialect `postgresql` |
| Database migrations complete | ✅ | `alembic_version=0001`; 3 tables + partial unique index present in PG; drift test passes on PG |
| Local test target can be registered | ✅ | smoke test: `http://testtarget:8080/...` via the private network |
| Monitoring measurements are stored | ✅ | 4 results 5 s apart, 2–4 ms, real HTTP to the `testtarget` container |
| Outage → incident after 2 failures | ✅ | opened at 2nd `HTTP 503` |
| 2 successes resolve the incident | ✅ | resolved at 2nd `200` |
| Results remain after container restart | ✅ | `compose restart`: 4→4. `compose down` + `up --build` (containers destroyed): 26→28 results, 2→2 targets, 2→2 incidents |
| Automated tests pass | ✅ | In container (PostgreSQL): **120 passed**. Locally (SQLite): 115 passed + 5 integration passed |
| Disallowed URLs are rejected | ✅ | 27 policy cases; live API returns 422 for `http://169.254.169.254/...` |
| README contains verified startup instructions | ✅ | Docker quick start and non-Docker paths both executed |

Security checks (live): only `api` is published, on `127.0.0.1:8000`. `docker port infrascope-db-1`
publishes nothing. `testtarget` has no internet access (internal network; DNS fails). Both
containers run as non-root (`infrascope`, `testtarget`).

## Completed work
- Config (pydantic-settings, `SecretStr` DB URL), Ruff + pytest config
- SQLAlchemy 2 models + Alembic migration `0001` (UUID PKs, UTC `timestamptz`, FKs, CHECKs,
  indexes, partial unique index for one OPEN incident per target)
- REST API: health, targets CRUD + results, incidents, summary; OpenAPI at `/docs`
- `HttpChecker` (httpx, streaming, no redirects, `trust_env=False`, timeout handling)
- Incident rules service (`record_check`) independent of the scheduler
- `MonitorEngine` background thread + pool, graceful start/stop via FastAPI lifespan
- SSRF URL policy, applied on write and before every check
- Test-target service, Dockerfiles (non-root), compose.yaml (127.0.0.1-only port, internal
  network, healthchecks, `pgdata` volume, test DB init script)
- `scripts/smoke-test.ps1` (with `-VerifyRestart`)
- Docs: README, ARCHITECTURE, API, this file

## Issues found and fixed during verification
- `TargetUpdate` fields were accidentally required (shared `Field` objects without defaults)
- `httpx` INFO logging printed every monitored URL → silenced to WARNING
- smoke-test.ps1: three Windows PowerShell 5.1 quirks (JSON arrays as one object; return
  unrolling; docker stderr treated as a terminating error) → fixed. The first one had made a
  check pass when it shouldn't
- pip "running as root" build warning → `PIP_ROOT_USER_ACTION=ignore`

## Commands executed (key ones)
```powershell
winget install -e --id Docker.DockerDesktop
docker compose up -d --build
docker compose ps
.\scripts\smoke-test.ps1 -VerifyRestart                 # PASSED
docker compose down; docker compose up -d --build --wait  # data persisted
docker compose exec api pytest -q                       # 120 passed (PostgreSQL)
.\.venv\Scripts\python.exe -m pytest -q                 # 115 passed, 5 skipped (SQLite)
.\.venv\Scripts\ruff.exe check .                        # clean
```

## Known problems / notes
1. Single API process only (in-process scheduler); documented in ARCHITECTURE.
2. No authentication — Day 2, by design.
3. Starlette TestClient emits an anyio deprecation warning (upstream, harmless).
4. On Windows, `localhost` checks against IPv4-only local servers add ~2 s (documented).
5. Port 5432 may already be taken on a developer machine by another PostgreSQL; InfraScope's
   database is never published, so there is no conflict (`docker port infrascope-db-1` is empty).

## Next task (Day 2)
1. Authentication/authorization for the API (API keys or OAuth2/JWT), with tests.
2. Frontend dashboard consuming `/api/v1/summary`, targets, results and incidents.
3. Optional: results retention, separate worker process, more target types.
