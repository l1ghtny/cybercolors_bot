# Durable messages, scheduled work, and attachments

Proposal for the next release, 16 September 2026. No durable queue or automatic history recovery is introduced by the service-status feature.

## Recommendation

Start with a PostgreSQL work ledger and leased workers, using the database already required for moderation. Reuse and strengthen the scheduled-post patterns. Keep a transport boundary so Kafka can be added if measurements justify a shared event log with multiple independent consumers. Evaluate Temporal if recurring schedules and multi-step recovery become a major subsystem.

This is a provisional architecture choice, not a capacity claim. Before selecting infrastructure, measure peak events/second, outage backlog size, oldest-job age, database write latency, number of independent consumers, and retained media volume. PostgreSQL explicitly supports `SKIP LOCKED` for queue-like tables ([PostgreSQL SELECT](https://www.postgresql.org/docs/current/sql-select.html)).

| Option | Useful for | Work still required |
| --- | --- | --- |
| PostgreSQL ledger + workers | Atomic message/job writes, delayed retries, moderate job volume, existing operational stack | Leases, fencing, retry policy, indexes, retention, monitoring, recovery tests |
| Kafka | Retained event streams, replay, independent consumers, partitioned ordering | Work/outcome ledger, delayed retry scheduling, external-effect deduplication, attachments, broker operations |
| Temporal | Durable multi-step workflows, long waits, recurring schedules and catch-up policies | Activity idempotency, external-effect reconciliation, media storage, workflow/version operations |

Kafka transactions do not make Discord sends or AI calls exactly once: its own design documents the need to coordinate external outputs with consumer position ([Kafka delivery semantics](https://kafka.apache.org/40/design/design/)). Temporal offers explicit schedule overlap and catch-up policies, which fit scheduled work, but those policies still need product decisions ([Temporal schedules](https://docs.temporal.io/schedule)).

## What already exists

- Message archival enters an in-memory queue; moderation is separate asynchronous work. Restarting can lose in-flight work. Provider errors do not create durable retry jobs.
- Discord may replay events when a gateway session resumes. A new session/restart has no application-level channel-history backfill. We cannot establish complete incident coverage from a recovered connection.
- `api/services/scheduled_posts.py` already stores schedules and run records, claims due work with `FOR UPDATE SKIP LOCKED`, and uses a lease. If a claimed run survives a worker crash, the next claim skips it to avoid sending twice. That trades a possible missed post for duplicate prevention; it is not guaranteed delivery. A normal failed delivery also advances the schedule rather than retrying that occurrence.
- Birthdays already persist greeting/role state and reconcile stale roles. Their triggering loops are process-local. A durable occurrence ledger would strengthen the remaining crash and scheduling boundaries, not replace existing birthday configuration.
- Scheduled-post attachments already use private S3-compatible object storage through `api/services/scheduled_post_storage.py`, with per-server keys and upload limits. Reuse the storage integration rather than add another provider.

## Message processing design

1. Persist the received message version and a moderation job atomically before acknowledging internal acceptance. Key jobs by `(server_id, message_id, content_version, pipeline_version)`. Hash text plus relevant attachment identifiers; edits can create a new version. Keep archival idempotent and independent of AI verdicts.
2. Store states `pending`, `running`, `retry_wait`, `completed`, `skipped`, `unavailable`, with attempt count, next attempt time, lease expiry, claim token, provider request identity, and coverage result. Persist clear verdicts even when verbose decision logging is disabled.
3. Claim a small batch in a short transaction, commit the lease, and release the connection before calling AI or Discord. Extend leases for long work. All completion writes must match the claim token so an expired worker cannot overwrite its replacement.
4. Use capped exponential retries with jitter, provider Retry-After handling, a retry budget, and a terminal review queue. Recheck server budget, exclusions, permissions, retention, and kill switches at execution. Record each billable attempt; a timeout can leave provider work completed and billed.
5. Give review cards, sanctions, replies, activity counters, and other effects their own deduplication keys. Do not treat a successful database claim as exactly-once delivery to Discord. Reconcile uncertain external sends before retrying; if no reliable reconciliation is possible, surface delivery as unknown for an operator decision.
6. Keep live traffic ahead of catch-up work with per-server fairness and cost caps. Measure queue age and incomplete coverage in addition to throughput.

### Outage recovery

Maintain a durable per-channel scan checkpoint and explicit coverage gaps. After stable connectivity, scan accessible history over the missing interval with overlap, pagination, permissions checks, and message-version deduplication. Include permitted threads deliberately; deleted content and inaccessible channels remain uncovered.

Do not replay old messages through the full `on_message` handler: that can duplicate automatic replies and activity counts. Historical processing should archive/review only, preserve original timestamps, label retrospective findings, and avoid automatic sanctions. It must not invent historical roles or rule context.

Proposed defaults to decide before implementation: automatic catch-up up to two hours/1,000 messages per server, bounded by the AI budget; larger gaps require a moderator-selected range and cost estimate. These limits are not currently implemented or promised.

## Durable birthdays and planned jobs

Create a unique occurrence per `(server, member, local birthday date, action kind)` and per scheduled-post occurrence. Store the timezone, scheduled instant, schedule revision, and latest useful execution time. Test daylight-saving transitions and leap-day policy explicitly.

Run a scheduler that inserts due occurrences idempotently and separate workers that execute them with leases. Greeting, role assignment, and role removal should be separate outcomes so a sent greeting does not prevent retrying a failed role update. Role cleanup should catch up after an outage; greetings should have an explicit same-day or maximum-lateness policy to avoid obsolete bursts.

Preserve existing birthday state and import pending work idempotently. Check schedule edits, pauses, deleted members, changed channels/roles, and bot permissions immediately before execution. Test a crash before sending, after sending but before saving, during a role update, and during lease replacement. Reconcile ambiguous sends rather than promise exactly-once messages.

## Attachments: build on the existing fixes

The user was right: attachment handling has already been improved, in two separate paths.

1. Moderation uses `prepare_ai_images_from_discord_message`: it downloads Discord attachments with `use_cached=True`, validates image bytes and MIME, applies per-image/total size and timeout limits, and passes inline image data. Missing media has an explicit unavailable flag. These bytes are ephemeral.
2. Scheduled-post uploads already survive restarts in object storage. This does not cover arbitrary incoming Discord message attachments.

Remaining gaps:

- Chat history/response paths and `ai_main.py` still call the older synchronous `ai_images_from_discord_message`, which can pass remote attachment URLs.
- The prepared moderation path can still include remote custom-emoji and image URLs found in text. The incident's exact failing URL was not captured, so we cannot attribute the provider 404 to a downloaded attachment specifically.
- `attachments_json` retains metadata/Discord URLs, not durable incoming binaries.

Proposed implementation sequence:

1. Move every AI message path onto the bounded asynchronous media preparation helper. Cover history, direct replies, moderation, custom emoji, and unavailable media with focused tests. Fetch only trusted Discord media domains server-side; arbitrary user URLs need a separately designed SSRF-safe fetcher or an explicit unsupported/unavailable result.
2. Before a message job becomes ready, persist required incoming media in the existing private object store. Store server-scoped object keys, content hash, detected type, byte size, retention expiry, and capture outcome in PostgreSQL. Queue messages carry keys, never base64 blobs or expiring CDN URLs. Bound receipt-time concurrency and storage per server.
3. Use an upload/finalization state and an orphan cleanup job because object storage and PostgreSQL do not share a transaction. Do not mark media ready until both object and metadata are durable. Check deletion/retention at processing and retry time.
4. Reuse storage credentials/infrastructure only after verifying its current permissions and retention settings; separate incoming-media prefixes and lifecycle rules from scheduled uploads. Keep download authorization tied to the server and use short-lived access only when needed.
5. Preserve partial/unavailable coverage when any required image is missing. A text-only fallback must not silently become a fully checked clear verdict. Permanent 404s need a bounded reference-refresh attempt, then a terminal unavailable result, not infinite retries.

## Release sequence and acceptance

1. Service-status indicator and runtime health (current change).
2. Unified media preparation and incoming object persistence.
3. Durable message ledger/worker, including full outcome records and idempotent effects.
4. Bounded historical catch-up and dashboard coverage reporting.
5. Durable scheduled occurrences for birthdays and strengthened scheduled posts.

Before choosing Kafka or another transport, run a recovery drill: terminate a worker during AI processing and between Discord send/database commit; interrupt gateway and REST access; fail media storage; replay duplicate/edited events; expire a lease while a worker is still running. Success means accounted-for outcomes and explicit unresolved gaps, not merely Ready pods or an empty queue.
