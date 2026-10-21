# Day 3 Progress — InfraScope

_Last updated: 2026-10-21. **Day 3 complete.**_

## 1. CI + Dependabot ✅
- `.github/workflows/ci.yml`: backend (ruff + pytest on a PostgreSQL 16 service with the real
  test target), frontend (audit, tsc, vitest, build), Docker Compose end-to-end (smoke test incl.
  restart persistence, suite in the container, CSP / 401 / network-isolation checks).
  Least-privilege permissions, masked secrets, timeouts, logs on failure.
- Evidence that the pipeline works: on its first day, CI ran on every Dependabot PR and passed
  the safe upgrades while **blocking 5 breaking ones** before they reached `main`.

## 2. Dependency upgrade ✅ (branch `deps/upgrade-2026-10`, merged to `main`)
Policy: newest stable release **at least 14 days old** (cutoff 2026-10-07), for supply-chain safety.

| Package | From | To |
|---|---|---|
| fastapi / starlette | 0.115.6 / 0.41 | 0.142.4 / 1.9.0 |
| uvicorn | 0.34.0 | 0.54.0 |
| SQLAlchemy | 2.0.36 | 2.1.4 |
| psycopg | 3.2.3 | 3.3.6 |
| alembic | 1.14.0 | 1.20.0 |
| pydantic / pydantic-settings | 2.10.4 / 2.7.1 | 2.13.5 / 2.15.0 |
| pytest / ruff | 8.3.4 / 0.8.4 | 9.1.1 / 0.16.10 |
| react / react-dom (+ types) | 18.3.1 | 19.3.0 |
| vite / @vitejs/plugin-react | 5.4.11 / 4.3.4 | 8.3.3 / 6.1.2 |
| vitest | 2.1.8 | 5.0.3 |
| typescript | 5.6.3 | 7.0.2 |
| nginx-unprivileged | 1.27-alpine | 1.29-alpine |

Why Dependabot's individual PRs failed, and what was fixed:
1. **FastAPI ≥0.140 nests included routers** (`_IncludedRouter`) instead of flattening them
   into `app.routes`. The auth route-walking test then found 0 routes, and its own
   `checked >= 10` guard caught it. Fix: walk nested routers too, and **cross-check against
   the public OpenAPI schema** so internal changes can't make the test silently check nothing.
2. **The frontend toolchain is peer-dependent** (Vite 8 ⇄ plugin-react 6 ⇄ Vitest 5), so
   single-package bumps can't install. Upgraded together; Dependabot now groups them.
3. Deprecations cleaned: `HTTP_422_UNPROCESSABLE_ENTITY` → `HTTP_422_UNPROCESSABLE_CONTENT`;
   Alembic `path_separator = os`.

Verification on the upgraded stack: ruff clean; pytest 136 + 5 skipped locally (SQLite) and
**141 passed in the container (PostgreSQL)**; frontend tsc (TS 7) clean, 49 tests, build OK,
`npm audit` 0 vulnerabilities; Docker smoke test incl. restart **PASSED**; dashboard
re-screenshotted on React 19 (light/dark/phone, tooltip works, no console or CSP errors).

## 3. Dependabot tuned ✅
Grouped minor/patch PRs per ecosystem, grouped frontend-toolchain majors, 14-day cooldown.

## Known follow-ups
- Starlette deprecation: test client prefers `httpx2` (README "What I'd do next").
- The old Dependabot PRs are superseded by the upgrade on `main`; Dependabot closes them
  automatically on its next run (or close them by hand).
- Repository is currently **private**: make it public before sharing it as a portfolio piece.
- `gh` CLI is not logged in, so CI results on GitHub could not be read from this machine.

## Next
Decide the direction: ITCore integration (start with ITCore as a monitored target), or
portfolio polish (demo GIF, About/topics, public visibility).
