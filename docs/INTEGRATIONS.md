# Integrating InfraScope with an internal IT portal

Three independent integrations; use any combination.

| | Direction | Use it to |
|---|---|---|
| [1. Monitor the portal](#1-monitor-the-portal) | InfraScope → portal | Detect when the portal itself is down |
| [2. Incident webhooks](#2-incident-webhooks) | InfraScope → portal | Create tickets/alerts in the portal when incidents open and resolve |
| [3. Read status from the API](#3-read-status-from-the-api) | portal → InfraScope | Show InfraScope's status and incidents on the portal's pages |

> Only connect systems you are authorised to monitor. Keep internal hostnames, IPs and secrets
> in `.env` on the server (git-ignored), never in the repository.

---

## 1. Monitor the portal

InfraScope only contacts explicitly allowlisted destinations (SSRF protection).

**If the portal has a hostname** (recommended), e.g. `portal.corp.example`:
```dotenv
ALLOWED_TARGET_HOSTS=testtarget,portal.corp.example
```

**If it is only reachable by IP**, opt in to that address or a narrow range:
```dotenv
ALLOWED_TARGET_NETWORKS=10.20.0.15/32
```
Ranges must be /16 or narrower (IPv6: /48). Loopback, link-local (including the cloud metadata
address `169.254.169.254`), multicast and unspecified addresses are refused even inside an
allowlisted range.

Then `docker compose up -d` and register the target (ADMIN key):
```powershell
$h = @{ "X-API-Key" = $env:INFRASCOPE_API_KEY }
$body = @{ name = "it-portal"; url = "https://portal.corp.example/health"; interval_seconds = 30 } | ConvertTo-Json
Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/v1/targets -Headers $h -ContentType application/json -Body $body
```
Pick a URL that is cheap to serve and doesn't need a login (a health or login page). A
redirect (3xx) counts as *up*, but InfraScope never follows it.

The API container must be able to reach the portal: run InfraScope on a machine inside the
same network, and check with
`docker compose exec api python -c "import httpx; print(httpx.get('https://portal.corp.example/health').status_code)"`.

---

## 2. Incident webhooks

### Configure
```dotenv
NOTIFY_WEBHOOK_URL=https://portal.corp.example/api/infrascope-events
NOTIFY_WEBHOOK_SECRET=<python -c "import secrets; print(secrets.token_urlsafe(32))">
```
The webhook host must also be in `ALLOWED_TARGET_HOSTS` (or its IP in `ALLOWED_TARGET_NETWORKS`);
InfraScope refuses to start otherwise. Restart with `docker compose up -d`, then send a test
event (ADMIN key):
```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/v1/notifications/test -Headers $h
Invoke-RestMethod http://127.0.0.1:8000/api/v1/notifications -Headers $h   # delivery status
```

### Delivery guarantees
- **Outbox:** each event is stored in the same database transaction as the incident change, so
  it is never lost by a crash or restart.
- **At-least-once:** failed deliveries (non-2xx, timeout, connection error) are retried after
  10 s, 20 s, 40 s, … up to 1 h between attempts, 8 attempts by default, then marked `FAILED`.
  `POST /api/v1/notifications/{id}/retry` re-queues one.
- Because a retry can repeat a delivery your endpoint already processed, **deduplicate on
  `X-InfraScope-Event-Id`**.
- Return any 2xx quickly (do the heavy work asynchronously). Redirects are not followed.

### Request
```http
POST /api/infrascope-events HTTP/1.1
Content-Type: application/json
User-Agent: InfraScope-Webhooks/0.3.0
X-InfraScope-Event: incident.opened            # incident.opened | incident.resolved | test
X-InfraScope-Event-Id: 6f1c0d3e-…              # unique per event; same on retries
X-InfraScope-Timestamp: 1761030000             # Unix seconds when this attempt was sent
X-InfraScope-Signature: sha256=5f2b…           # present when NOTIFY_WEBHOOK_SECRET is set
```
```json
{
  "event_id": "6f1c0d3e-…",
  "type": "incident.opened",
  "occurred_at": "2026-10-21T07:02:02.820832Z",
  "source": "infrascope",
  "version": "0.3.0",
  "incident": {
    "id": "a3e9…", "status": "OPEN",
    "opened_at": "2026-10-21T07:02:02.820832Z", "resolved_at": null,
    "failure_reason": "HTTP 503", "resolution_reason": null
  },
  "target": { "id": "7d5b…", "name": "it-portal", "url": "https://portal.corp.example/health", "status": "DOWN" }
}
```
`incident.resolved` has the same shape, with `status: "RESOLVED"`, `resolved_at` set and a
`resolution_reason` (e.g. *Recovered after 2 consecutive successful checks* or *Target
deleted*). `test` events have only `event_id`, `type`, `occurred_at`, `source`, `version`,
`message`.

### Verify the signature (do this before trusting the body)
`signature = "sha256=" + hex(HMAC_SHA256(secret, "<timestamp>.<raw request body>"))`

Compare in **constant time**, over the **raw body bytes** (before JSON parsing), and reject
timestamps more than 5 minutes from now (replay protection).

**Python**
```python
import hashlib, hmac, time


def verify(secret: str, timestamp: str, raw_body: bytes, signature: str) -> bool:
    if abs(time.time() - int(timestamp)) > 300:
        return False
    expected = (
        "sha256="
        + hmac.new(secret.encode(), f"{timestamp}.".encode() + raw_body, hashlib.sha256).hexdigest()
    )
    return hmac.compare_digest(expected, signature)
```

**Node.js**
```js
const crypto = require("node:crypto");

function verify(secret, timestamp, rawBody /* Buffer */, signature) {
  if (Math.abs(Date.now() / 1000 - Number(timestamp)) > 300) return false;
  const mac = crypto.createHmac("sha256", secret).update(`${timestamp}.`).update(rawBody).digest("hex");
  const expected = Buffer.from(`sha256=${mac}`);
  const given = Buffer.from(signature || "");
  return expected.length === given.length && crypto.timingSafeEqual(expected, given);
}
```

**C# (.NET)**
```csharp
using System.Linq;
using System.Security.Cryptography;
using System.Text;

static bool Verify(string secret, string timestamp, byte[] rawBody, string signature)
{
    if (Math.Abs(DateTimeOffset.UtcNow.ToUnixTimeSeconds() - long.Parse(timestamp)) > 300) return false;
    using var hmac = new HMACSHA256(Encoding.UTF8.GetBytes(secret));
    var data = Encoding.UTF8.GetBytes(timestamp + ".").Concat(rawBody).ToArray();
    var expected = "sha256=" + Convert.ToHexString(hmac.ComputeHash(data)).ToLowerInvariant();
    return CryptographicOperations.FixedTimeEquals(Encoding.UTF8.GetBytes(expected), Encoding.UTF8.GetBytes(signature ?? ""));
}
```

**PHP**
```php
function verify(string $secret, string $timestamp, string $rawBody, string $signature): bool {
    if (abs(time() - (int)$timestamp) > 300) return false;
    $expected = 'sha256=' . hash_hmac('sha256', $timestamp . '.' . $rawBody, $secret);
    return hash_equals($expected, $signature);
}
```

`app/services/notifications.py::verify_signature` is the reference implementation, covered by
the test suite. The Python and Node.js snippets above were checked against signatures it
produced (valid accepted, tampered body rejected); the C# and PHP snippets follow the same
algorithm but have not been executed in this project, so test them against
`POST /api/v1/notifications/test` before relying on them.

---

## 3. Read status from the API

1. Create a **read-only** key for the portal (it can read but never change anything):
   ```powershell
   docker compose exec api python -m app.cli create-api-key --name it-portal --role VIEWER
   ```
2. Call the API from the portal's **server side** (never embed the key in browser JavaScript):

   | Endpoint | Returns |
   |---|---|
   | `GET /api/v1/summary` | Counts by status, open incidents, checks and failures in the last 24 h, average response time |
   | `GET /api/v1/targets` | Every target with its current status |
   | `GET /api/v1/incidents?status=OPEN` | Current outages |
   | `GET /api/v1/targets/{id}/results?limit=50` | Recent checks for one target |

   ```python
   import httpx

   summary = httpx.get(
       "https://infrascope.corp.example/api/v1/summary",
       headers={"X-API-Key": INFRASCOPE_VIEWER_KEY},
       timeout=5,
   ).json()
   ```
   Full reference: [API.md](API.md) or `/docs` on the running instance.

3. **Making the API reachable from another server.** By default the API is published on
   `127.0.0.1` only. To let the portal's server reach it:
   - put a TLS-terminating reverse proxy (nginx, Caddy, IIS ARR…) in front, with a certificate
     the portal trusts;
   - set `API_BIND` in `.env` to the host's internal address (not `0.0.0.0` on a multi-homed
     machine), or keep `127.0.0.1` and let the proxy on the same host forward to it;
   - firewall the port so only the portal's server can connect.

   Revoke a key at any time with `python -m app.cli revoke-api-key <id>` or
   `DELETE /api/v1/api-keys/{id}`.

---

## Security checklist
- [ ] Authorised to monitor/integrate with the portal
- [ ] Only the portal's hostname (or a `/32`) added to the allowlists
- [ ] `NOTIFY_WEBHOOK_SECRET` set; the portal verifies the signature and timestamp
- [ ] The portal deduplicates on `X-InfraScope-Event-Id`
- [ ] The portal uses a `VIEWER` key, stored server-side
- [ ] API exposed beyond localhost only behind TLS and a firewall
- [ ] No internal hostnames, IPs or secrets committed to git
