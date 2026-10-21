# InfraScope Architecture (Day 1)

## Components

```mermaid
flowchart TB
    subgraph api["api container (single uvicorn worker)"]
        direction TB
        routes["FastAPI routers<br/>health · targets · incidents · summary"]
        policy["url_policy<br/>SSRF allowlist"]
        subgraph mon["MonitorEngine (background thread)"]
            sched["scheduler loop<br/>tick = 1 s"]
            pool["ThreadPoolExecutor<br/>(8 workers)"]
        end
        checker["HttpChecker<br/>httpx · no redirects · timeout 5 s"]
        rules["incidents.record_check()<br/>pure incident rules"]
        routes --> policy
        sched --> pool --> policy
        pool --> checker
        pool --> rules
    end
    db[("PostgreSQL 16<br/>monitoring_targets<br/>monitoring_results<br/>incidents")]
    tt["testtarget<br/>/healthy · /unhealthy · /slow"]
    routes -->|"SQLAlchemy 2 / psycopg 3"| db
    rules --> db
    checker -->|"HTTP via private network"| tt
```

### Request path
FastAPI endpoints are plain `def` functions, so FastAPI runs them in its threadpool with a
SQLAlchemy session per request (`app/api/deps.py`). Target URLs go through
`validate_target_url()` before they are stored.

### Authentication (`app/api/auth.py`, `app/services/api_keys.py`)
- Keys are `isk_` + 32 random bytes (url-safe base64), generated with `secrets`.
- Only `sha256(key)` is stored, with a unique index; lookup is by hash, so no plaintext
  comparison happens. A slow password hash (bcrypt/argon2) adds nothing for 256-bit random
  secrets and would cost CPU on every request.
- `require_viewer` resolves the key (rejecting revoked and expired keys) and is attached to
  each protected router; write routes add `require_admin`. FastAPI caches the dependency, so
  the key is looked up once per request.
- `last_used_at` is written at most once per minute per key, to avoid a write on every read.
- The first ADMIN key comes from the CLI (`python -m app.cli`), so no bootstrap secret lives
  in configuration.

```mermaid
erDiagram
    api_keys {
        uuid id PK
        varchar name
        varchar key_prefix "first 12 chars, non-secret"
        varchar key_hash UK "sha256 hex"
        varchar role "VIEWER|ADMIN"
        timestamptz created_at
        timestamptz expires_at
        timestamptz last_used_at
        timestamptz revoked_at
    }
```

### Monitoring path
1. `MonitorEngine` runs in its own daemon thread. It is started and stopped by the FastAPI
   lifespan, so it never blocks the event loop or API requests.
2. Every tick it loads enabled targets and selects those where
   `now - last_checked_at >= interval_seconds` (or that have never been checked).
3. Each due target is checked on the thread pool:
   - the URL policy is re-applied (an allowlist change takes effect immediately; blocked
     targets are recorded as failures without any network request);
   - `HttpChecker` does a streaming GET and measures time until response headers with
     `time.perf_counter()`. Bodies are never downloaded, redirects are never followed,
     keep-alive is disabled so each measurement includes connection setup, and proxy env vars
     are ignored;
   - the outcome is persisted in its own transaction with `SELECT … FOR UPDATE` on the target
     row. If the target was deleted, disabled or re-pointed mid-check, the result is discarded.
4. On shutdown, `stop()` sets an event, joins the scheduler thread and waits for in-flight
   checks (bounded by the HTTP timeout).

### Incident rules (`app/services/incidents.py`)

```mermaid
stateDiagram-v2
    [*] --> UNKNOWN
    UNKNOWN --> UP: success
    UP --> DOWN: 2nd consecutive failure / open incident
    UNKNOWN --> DOWN: 2nd consecutive failure / open incident
    DOWN --> DOWN: 1st success (incident stays open)
    DOWN --> UP: 2nd consecutive success / resolve incident
```

- A single failure never changes status (flap protection).
- An incident is only opened if none is open for that target. The partial unique index
  `uq_incidents_open_per_target (target_id) WHERE status = 'OPEN'` enforces this in the DB.
- `failure_reason` is the reason from the check that confirmed the outage (e.g. `HTTP 503`,
  `Timeout after 5s`, `Connection failed: …`).
- Thresholds are configurable (`FAILURE_THRESHOLD`, `RECOVERY_THRESHOLD`).
- `record_check()` takes a session, a target and an outcome. It has no scheduler or network
  dependency, so it is unit-tested directly.

## Data model

```mermaid
erDiagram
    monitoring_targets ||--o{ monitoring_results : "has (ON DELETE CASCADE)"
    monitoring_targets |o--o{ incidents : "has (ON DELETE SET NULL)"
    monitoring_targets {
        uuid id PK
        varchar name UK
        varchar url UK
        varchar target_type "HTTP"
        int interval_seconds "5..3600"
        bool enabled
        varchar status "UP|DOWN|UNKNOWN"
        int consecutive_failures
        int consecutive_successes
        timestamptz created_at
        timestamptz updated_at
        timestamptz last_checked_at
    }
    monitoring_results {
        uuid id PK
        uuid target_id FK
        timestamptz checked_at
        bool success
        int status_code
        float response_time_ms
        varchar error
    }
    incidents {
        uuid id PK
        uuid target_id FK "nullable"
        varchar target_name "snapshot"
        varchar status "OPEN|RESOLVED"
        timestamptz opened_at
        timestamptz resolved_at
        varchar failure_reason
        varchar resolution_reason
    }
```

- Enums are stored as `VARCHAR` + `CHECK` (not native PG enums) to keep migrations simple.
- All timestamps are `timestamptz`. The `UTCDateTime` type rejects naive datetimes and always
  returns aware UTC values.
- Indexes: `(target_id, checked_at)` for result history, `checked_at` for the 24-hour summary,
  `(enabled, status)` on targets, `(status, opened_at)` and `target_id` on incidents.
- Deleting a target cascades its results, but **keeps its incidents**. `target_id` becomes
  NULL, `target_name` is a snapshot, and any open incident is resolved with
  `resolution_reason = "Target deleted"`.
- `tests/test_persistence.py` runs Alembic upgrade/downgrade and asserts there is no drift
  between the models and the migration.

## Dashboard (`frontend/`)

- React 18 + TypeScript, built by Vite into static files served by an unprivileged nginx
  container (`web`). nginx also reverse-proxies `/api/` and `/health` to `api:8000`, so the
  browser only ever talks to one origin and no CORS configuration exists. In development,
  Vite's proxy reproduces the same setup.
- Data refreshes by polling every 5 s, paused while the tab is hidden. Previous data stays on
  screen during a refetch (no flashing). Any 401 signs the user out.
- Write controls (add, pause, delete) render only for ADMIN keys. The API enforces this
  independently; the UI just avoids offering actions that would fail with 403.
- The response-time chart is hand-built SVG, so there is no charting dependency. Geometry lives in
  `src/chart.ts` (pure, unit-tested). Colors come from a validated palette: one series hue
  plus the reserved status colors, CVD-checked in light and dark mode. Status is never color
  alone (badges have an icon and a label). The chart supports hover and keyboard
  (arrow keys) readout, and the check table under it is its text alternative.

## Security boundaries

| Boundary | Control |
|---|---|
| Host → API | Published on `127.0.0.1` only; `X-API-Key` required on everything except `/health` and docs |
| Authorization | `VIEWER` = read; `ADMIN` = write + key management; enforced by router-level dependencies, and a test fails if any non-public route is reachable without a key |
| Host → DB / testtarget | Not published at all |
| Containers → internet/LAN | `db` and `testtarget` are on an `internal: true` network |
| API → monitored URL (SSRF) | Hostname allowlist; no IP literals, userinfo, non-HTTP schemes, control chars; checked on write **and** before every request; redirects disabled; `trust_env=False` |
| Secrets | `.env` git-ignored; `DATABASE_URL` is a `SecretStr`; `httpx` request logging silenced |
| Browser ↔ dashboard | Strict CSP (`script-src 'self'`, no inline scripts, `frame-ancestors 'none'`), `nosniff`, `no-referrer`; key in `sessionStorage` |
| Dashboard → backend | `web` is only on the `edge` network: it can reach `api`, not `db` or `testtarget` |
| Containers | Non-root users in all images |

Residual risk: the allowlist trusts Docker's DNS for the allowlisted names. That is acceptable
for a private Compose network, but must be revisited before monitoring external hosts (Day 2+:
resolve-then-pin with IP range checks).

## Known limitations / design decisions

- **Single process.** The scheduler runs inside the API process (`--workers 1`). Several
  replicas would double-check targets. Scaling out needs a separate worker service with
  `SELECT … FOR UPDATE SKIP LOCKED` leasing or a distributed lock.
- Due-target selection loads all enabled targets each tick. Fine for hundreds of targets; for
  more, push the due filter into SQL.
- Results grow unbounded; retention/downsampling is future work.
- Only `HTTP` targets. TCP, ICMP, DNS and TLS-expiry checks are planned (`TargetType` enum).
