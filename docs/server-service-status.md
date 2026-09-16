# Server service status

Implemented contract, 16 September 2026. This reports connection and task health; it is not a message-processing ledger.

## Dashboard API

`GET /servers/{server_id}/service-status` uses the existing authenticated dashboard session, application-surface check, and server dashboard-access check. It returns `Cache-Control: private, no-store`. Unauthorized requests cannot read runtime data. Existing permission verification can depend on Discord when its cache expires; errors remain errors and the UI displays unknown status.

```json
{
  "state": "degraded",
  "observed_at": "2026-09-16T12:00:00Z",
  "expires_at": "2026-09-16T12:01:30Z",
  "components": [
    {"id": "gateway", "state": "healthy", "reason": null},
    {"id": "commands", "state": "retrying", "reason": null},
    {"id": "moderation_expiry", "state": "healthy", "reason": null},
    {"id": "birthdays", "state": "healthy", "reason": null}
  ],
  "discord_incident": null,
  "discord_status_observed_at": "2026-09-16T11:59:50Z"
}
```

- Overall states: `healthy`, `reconnecting`, `degraded`, `unknown`.
- Component states: `healthy`, `reconnecting`, `retrying`, `unavailable`, `unknown`.
- A fresh advisory contains `title`, canonical `url`, and upstream `status`. It never changes this server's operational state.
- Null report timestamps mean no report exists. An expired report retains its timestamp, but all component states become unknown with `reason: stale_report`.
- Neither process identifiers, profile names, shard numbers, nor other guild IDs appear in the public response.

## Runtime collection and state selection

Each bot starts an independent reporter in `setup_hook`, before cache initialization and READY. It writes one PostgreSQL row per application profile, nominally every 20 seconds, with a ten-second bound per publication. Both API replicas read the same rows.

The API resolves `Server.bot_profile`, then `(server_id >> 22) % shard_count`. A connected shard requires an open websocket and a finite heartbeat latency. Discord's per-guild unavailable flag overrides a healthy shard. A guild absent from the selected bot's cache is unknown. Failed server-assignment refresh also prevents a healthy message-monitoring result.

Command registration has explicit retrying/success/permanent-failure states. Background loops are checked for running/failed status, uncaught run failures, and execution duration (120 seconds for assignment refresh, five minutes for moderation expiry, 30 minutes for birthday tasks). A scheduled loop waiting until its next run is healthy. A caught per-item delivery failure is not necessarily a failed loop: this endpoint does not claim successful delivery of every scheduled action.

Reports expire after 90 seconds. Observations more than 30 seconds in the future are rejected. Process start time and identity fence writes from replaced processes; this assumes synchronized host clocks. State changes are recorded in application logs, without message content. The database holds the latest snapshot, not a historical incident ledger.

Official Discord incidents are fetched by the bot reporters from the fixed unresolved-incidents endpoint, with a shared PostgreSQL claim limiting attempts to one per minute. Fetches have a five-second timeout and 128 KiB response cap. Errors preserve the last successful observation; advisory data expires after five minutes. Links are constructed from validated incident IDs.

The dashboard polls every 30 seconds while active and checks cached report expiry every second and on focus/visibility changes. A failed request immediately yields unknown, including when React Query retains old successful data. Switching servers uses a separate cache key. The indicator and conditional banner reflect current observations directly; no delayed recovery or historical coverage claim is made.

## Operational checks

- Bot port 9101: `/livez` checks the event loop/reporter task, independently of Discord and PostgreSQL. `/readyz` also checks startup and critical background loops; command registration can keep retrying independently.
- Both bot Deployments have startup, liveness, and readiness probes. Readiness failures do not restart the process. Metrics services publish unready endpoints so failed workers remain visible to Prometheus.
- Prometheus rules cover a disconnected shard for three minutes, unhealthy components for five minutes, stale runtime reports for two minutes beyond expiry, and failed metrics scrapes for two minutes. Existing cluster-level missing-pod monitoring remains necessary when no scrape target exists.
- Runtime metrics and logs expose partial recovery without creating a Sentry event for every retry. Permanent command errors remain visible through the existing error path.

## Rollout and verification

1. Apply migration `a71c293dd420` before deploying either bot or API. It adds two tables and the bilingual in-product release note.
2. Deploy backend/API, both bots, and the dashboard through the normal release pipeline; apply the bot probe and PrometheusRule manifests.
3. Check both profiles publish fresh rows, both bot probes behave as intended, and Prometheus discovers the rules and targets.
4. Check the authenticated endpoint for a server on each profile. Verify the rendered indicator against the selected shard and worker state.
5. A local component preview and passing tests do not establish these production checks. Do not claim complete message catch-up from a healthy indicator.

The database change is additive. An application rollback can leave the new tables and release row in place; remove them only through a deliberate migration rollback.

## Implementation validation

- 42 focused backend checks passed in a disposable PostgreSQL schema, including process replacement, concurrent advisory polling, API access rejection, per-shard selection, stale reports, worker health, command retries, and release-note ordering. The test schema was dropped.
- Alembic has one head; the new migration renders offline. Kubernetes manifests render with Kustomize. Prometheus rules are prepared but not yet validated against live scrape targets.
- Dashboard tests and the normal production build pass. The explicit `tsc --project tsconfig.app.json --noEmit` check still reports existing errors; its output is identical to an untouched baseline at `cbb0ba9`.
- The real status components were inspected in English and Russian at desktop and mobile widths, including 320 pixels. The development-only `service-status-preview.html` uses sample data and is not a production entry point.
