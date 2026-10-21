# InfraScope API (v1)

Base URL: `http://127.0.0.1:8000`. Interactive OpenAPI docs: `/docs` (raw schema: `/openapi.json`).

**No authentication on Day 1.** Localhost-only development API.

All timestamps are ISO 8601 UTC. IDs are UUIDs. Errors use FastAPI's format:
`{"detail": "..."}`, or a list of validation errors for 422.

## Health

### `GET /health`
`200` when the database answers `SELECT 1`, otherwise `503`.

```json
{ "status": "ok", "database": "ok", "monitor": "running", "version": "0.1.0" }
```
`monitor` is `running`, `stopped` or `disabled`.

## Targets

### Target object
```json
{
  "id": "d3dd1d46-513b-4120-af93-3fdc2bb0d715",
  "name": "web-healthy",
  "url": "http://testtarget:8080/healthy",
  "target_type": "HTTP",
  "interval_seconds": 30,
  "enabled": true,
  "status": "UNKNOWN",
  "consecutive_failures": 0,
  "consecutive_successes": 0,
  "created_at": "2026-10-21T05:15:44.991Z",
  "updated_at": "2026-10-21T05:15:44.991Z",
  "last_checked_at": null
}
```

### `POST /api/v1/targets` → `201`
| Field | Type | Rules |
|---|---|---|
| `name` | string | required, 1–100 chars, unique |
| `url` | string | required, ≤2048 chars, must pass the URL policy, unique after normalization |
| `target_type` | string | optional, only `HTTP` |
| `interval_seconds` | int | optional, 5–3600, default 30 |
| `enabled` | bool | optional, default `true` |

Unknown fields are rejected. Errors: `422` invalid/disallowed URL, `409` duplicate name or URL.

```powershell
$body = @{ name = "web-healthy"; url = "http://testtarget:8080/healthy"; interval_seconds = 10 } | ConvertTo-Json
Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/v1/targets -ContentType application/json -Body $body
```

URL policy: scheme `http`/`https`; hostname in `ALLOWED_TARGET_HOSTS`; no IP addresses; no
`user:pass@`; no whitespace, backslashes or control characters. The URL is normalized:
lowercase scheme and host, fragment removed.

### `GET /api/v1/targets` → `200`
Query: `enabled` (bool), `status` (`UP`|`DOWN`|`UNKNOWN`), `limit` (1–500, default 100), `offset`.
Ordered by creation time.

### `GET /api/v1/targets/{id}` → `200` | `404`

### `PATCH /api/v1/targets/{id}` → `200` | `404` | `409` | `422`
Any subset of `name`, `url`, `interval_seconds`, `enabled`. `null` values are rejected.
Enable/disable monitoring:
```powershell
Invoke-RestMethod -Method Patch "http://127.0.0.1:8000/api/v1/targets/$id" -ContentType application/json -Body '{"enabled": false}'
```
Changing `url` resets the consecutive-success/failure counters.

### `DELETE /api/v1/targets/{id}` → `204` | `404`
Deletes the target and its results. Incidents are **kept**: `target_id` becomes `null`, and any
open incident is resolved with `resolution_reason: "Target deleted"`.

### `GET /api/v1/targets/{id}/results` → `200` | `404`
Newest first. Query: `limit` (1–1000, default 100), `offset`.
```json
[{
  "id": "…", "target_id": "…", "checked_at": "2026-10-21T05:15:50.210224Z",
  "success": false, "status_code": 503, "response_time_ms": 15.28, "error": "HTTP 503"
}]
```
`status_code` and `response_time_ms` are `null` when no HTTP response arrived (timeout or
connection error). `response_time_ms` is the time until response headers, including connection
setup.

## Incidents

### `GET /api/v1/incidents` → `200`
Newest first. Query: `status` (`OPEN`|`RESOLVED`), `target_id`, `limit` (1–500), `offset`.
```json
[{
  "id": "…", "target_id": "…", "target_name": "smoke-131544", "status": "RESOLVED",
  "opened_at": "2026-10-21T05:15:50.210224Z", "resolved_at": "2026-10-21T05:16:00.443861Z",
  "failure_reason": "HTTP 503",
  "resolution_reason": "Recovered after 2 consecutive successful checks"
}]
```

## Summary

### `GET /api/v1/summary` → `200`
```json
{
  "targets_total": 3, "targets_enabled": 3,
  "targets_by_status": { "UP": 2, "DOWN": 1, "UNKNOWN": 0 },
  "open_incidents": 1,
  "checks_last_24h": 58, "failed_checks_last_24h": 22,
  "avg_response_time_ms_last_24h": 12.75,
  "generated_at": "2026-10-21T05:16:13.193801Z"
}
```

## Test target service (internal only)

Reachable only from the Compose network at `http://testtarget:8080`:

| Endpoint | Response |
|---|---|
| `GET /healthy` | `200 {"status":"healthy"}` |
| `GET /unhealthy` | `503 {"status":"unhealthy"}` |
| `GET /slow` | `200` after `SLOW_DELAY_SECONDS` (default 3); `?delay=0..30` overrides |
