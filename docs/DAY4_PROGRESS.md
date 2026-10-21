# Day 4 Progress — InfraScope

_Last updated: 2026-10-21_

## A. Portfolio-ready ✅
- Pre-publication audit of the full git history: no secrets (two pattern hits were a `sed`
  template and the `isk_xxxx…` docs placeholder); workstation-specific details removed and
  history rewritten (final tree verified identical, 0 matches left in reachable history).
- Repository made public; CI green on GitHub (backend, frontend, Docker end-to-end).
- README: live demo GIF (scripted outage → incident → recovery on the real stack).
- Chart fix found while recording: y-axis ticks are now clean numbers (`niceTicks`).
- Detail panel refetches when the target's last check changes (no lag vs. status badge).

## B. Integration with an internal IT portal ✅ (v0.3.0)
1. **Monitor by IP (opt-in)**: `ALLOWED_TARGET_NETWORKS` (≥ /16 IPv4, ≥ /48 IPv6).
   Loopback, link-local/metadata, multicast, unspecified and reserved addresses are refused
   even inside an allowlisted range (including IPv4-mapped IPv6 like `::ffff:127.0.0.1`).
2. **Incident webhooks**: transactional outbox (`notification_events`, migration 0003),
   HMAC-SHA256 signature over `timestamp.body` (replay window 5 min), retries with exponential
   backoff (10 s → 1 h cap, 8 attempts), redirects not followed, destination checked by the
   same SSRF policy; startup fails fast on a disallowed webhook URL. Admin endpoints:
   `/api/v1/notifications` (+ `/config`, `/test`, `/{id}/retry`). Deleting a target with an
   open incident emits `incident.resolved`.
3. **Status for the portal**: VIEWER key + existing API; `API_BIND` to publish beyond
   localhost (documented: TLS + firewall).
4. `docs/INTEGRATIONS.md`: setup, payload schema, delivery guarantees, signature verification
   in Python / Node.js / C# / PHP (Python and Node.js verified against real signatures; C# and
   PHP not executed: no .NET SDK / PHP here), security checklist.

### Bugs found and fixed while building B
- Outbox row was inserted before its new incident (FK violation): SQLAlchemy orders INSERTs
  by relationships, not bare foreign keys → added `NotificationEvent.incident` relationship.
- Tests weren't hermetic: inside the container `NOTIFY_WEBHOOK_URL` is set and
  pydantic-settings reads it for any field a test doesn't pass → all env-sensitive fields are
  now pinned in `make_settings`; verified by running the suite with hostile env vars.
- A blank `NOTIFY_WEBHOOK_SECRET` (Compose passes unset vars as "") counted as a signing key
  → blank now means unsigned (with a startup warning).

### Verification
- Local: ruff clean; **175 passed** + integration **6 passed** against the real test target
  (incl. signed webhook over HTTP and the failure/retry path).
- Docker (PostgreSQL, migration 0003 applied to existing data): smoke test PASSED with
  webhooks on; `incident.opened` + `incident.resolved` DELIVERED on attempt 1, signatures
  valid at the receiver; **181 passed** in the container.
- CI: new step verifies delivered webhooks and their signatures on every push.

## Live state
- Stack running with the owner's `.env` (webhooks **off**); temporary keys revoked; active
  keys: the owner's own.

## Notes
- The portal's real hostname/IP, webhook URL and secrets belong only in the server's `.env`.
- Day 3's progress note (already public) named the portal; the current file is fixed. The
  older commit still contains the name (no hostnames, IPs or credentials).

## Next
- Owner: point InfraScope at the portal (see `docs/INTEGRATIONS.md`, section 1) and build
  the portal's webhook receiver (section 2).
- Optional: Slack/e-mail channels, per-target routing; `httpx2` migration.
