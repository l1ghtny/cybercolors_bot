# Roll out indexed Discord identity retrieval

The implementation adds a PostgreSQL GIN identity index alongside existing pgvector content retrieval. Migration `e1c7a4b9d620` creates the alias projection and its maintenance triggers. Existing member aliases are populated by the backfill command. Content does not need to be re-embedded.

Identity retrieval is opt-in through `AI_KNOWLEDGE_IDENTITY_SERVER_IDS`. An unset or empty value uses the previous retrieval behavior. Set a comma-separated list of Discord server IDs on both the API and bot processes to enable the shared path for those servers; `*` enables every server. Moderation and explicitly scoped transcript tool searches keep their semantic retrieval policy.

## Implementation evidence, 2026-09-04

The backend implements alias projection maintenance, shared retrieval, ambiguity handling, account-name event refresh, and resumable backfill. The dashboard displays identity evidence, account choices, and partial results while accepting responses from the previous backend version.

PostgreSQL 18.3 with pgvector passed the database integration suite in a fresh disposable schema. Fixtures cover unchanged biographies, exact and in-question aliases, handle punctuation, ambiguous members without KB entries, source visibility and scope, outages, transaction timeout recovery, concurrent name updates/backfill, migration reversal, and parity between dashboard search, AI tools, and answer preloading. The focused backend and release-note suite passed 75 tests; the dashboard passed five tests, TypeScript checking, and its production build. Alembic has one head and the upgrade renders offline.

The scale fixture contains 100,001 members, including 50 people sharing `May`. Forty alternating selective-handle/common-name lookups measured 55.98 ms median and 66.51 ms p95; the first cold lookup took 105.93 ms. Both equality and GIN plans used the intended indexes. Database execution times for the isolated equality, sentence, and common-name predicates were 0.014, 3.83, and 4.68 ms respectively.

These measurements came from the macOS ARM64 development workstation against the configured remote PostgreSQL server, with an observed approximately 25 ms database round trip; server CPU and memory were not inventoried. They measure `search_identity_aliases`, including both SQL round trips, and exclude connection establishment, retrieval savepoints, embeddings, subject passage ranking, and answer generation. The 40-sample p95 includes the cold sample. This is fixture evidence, not a production capacity or end-to-end latency claim.

Release-note decision: this corrects user-visible KB lookup and needs an in-product note once enabled. It does not introduce a substantial new workflow warranting a public product update. The schema migration contains the bilingual note as an unpublished, non-public draft. No production migration, backfill, activation, or live Discord answer verification was performed during implementation.

## Deployment sequence

1. Deploy the dashboard version that handles nullable semantic scores and the new result metadata.
2. Confirm the target database and schema using the deployment's existing environment, then apply migration `e1c7a4b9d620` through the normal migration job. The migration changes canonical account/membership tables only by attaching projection-maintenance triggers.
3. Backfill the pilot server's retained memberships. The script requires either an explicit server ID or `--all-servers`; it does not select a target implicitly.
4. Audit linked KB accounts and refresh their Discord profiles where needed. Names copied into the identity table from an old canonical record are still old names.
5. Enable the server ID on the API and bot after the frontend and backfill are ready.
6. Verify an unchanged linked biography in authenticated dashboard search and an authorized Discord test. Confirm returned source IDs and answer attribution, including an ambiguous-name case.
7. Publish draft release note `2026-09-04-knowledge-discord-identities` through the release process after the capability is enabled and runtime verification passes. The migration prepares it with `is_published=false` and `is_public=false`.

From the backend checkout, with its normal deployment environment loaded, replace the example ID with the intended server ID:

```sh
TARGET_GUILD_ID=123456789012345678
.venv/bin/python scripts/backfill_knowledge_identities.py --server-id "$TARGET_GUILD_ID"
.venv/bin/python scripts/backfill_knowledge_identities.py --server-id "$TARGET_GUILD_ID" --check
```

The audit reports linked accounts with missing memberships, usernames, or alias rows. It does not expose credentials or biography contents. `--check` performs no writes.

To refresh linked accounts from Discord and reconcile their aliases:

```sh
.venv/bin/python scripts/backfill_knowledge_identities.py --server-id "$TARGET_GUILD_ID" --refresh-linked --refresh-limit 100
```

This operation uses the existing Discord member-fetching and profile-hydration path, with its configured bot access. It reports unavailable profiles separately. If `refresh_truncated` is true, resume with `--refresh-after-user-id` set to the returned `refresh_after_user_id`. To resume an interrupted alias backfill, use `--after-user-id` from its last committed batch. The two cursors are independent. Re-running a full backfill also repairs missing/stale projection rows without changing unchanged aliases' timestamps.

## Runtime behavior

- Complete account-name queries and mentions can retrieve linked facts even with low semantic similarity.
- Names inside questions are indexed candidates. The answer context explicitly distinguishes a possible name reference from a definite target.
- Exact handle spelling is checked after indexed candidate retrieval, preserving distinctions such as `foo_bar` versus `foo bar`.
- Ambiguous aliases are checked against retained directory members, including people without KB entries. Selecting an account grants no additional access.
- Source server, visibility, ready status, deletion state, and source-ID restrictions apply to both retrieval branches.
- An embedding outage can return identity matches with null semantic scores. Database branch failures roll back to savepoints, and partial results identify the unavailable component.
- Identity statements have a 1.5-second database timeout, respecting any lower existing timeout. Candidate and output limits are also bounded.

Remove a server ID from `AI_KNOWLEDGE_IDENTITY_SERVER_IDS` on both processes to roll back its retrieval behavior. Keep the additive schema and aliases while diagnosing a problem. A rollout rollback does not require dropping account data or reindexing content.

## Verification commands

The database integration suite requires PostgreSQL with pgvector and an unused `cybercolors_test_identity_*` schema name. It creates all fixture tables in that schema and drops the schema afterward. It refuses to reuse an existing schema. Supply the intended test database connection through the usual environment; no production schema is selected by these commands.

```sh
DB_SCHEMA=cybercolors_test_identity_manual .venv/bin/python -m pytest -q tests/test_knowledge_identities.py
DB_SCHEMA=cybercolors_test_identity_scale KNOWLEDGE_IDENTITY_BENCHMARK=1 .venv/bin/python -m pytest -q -s tests/test_knowledge_identities.py
.venv/bin/python -m pytest -q tests/test_ai_module.py tests/test_nickname_history.py tests/test_youtube_channel_catalog.py
.venv/bin/alembic heads
.venv/bin/alembic upgrade 49703b66f5d6:e1c7a4b9d620 --sql
```

The scale run creates 100,000 synthetic members in the disposable schema and prints lookup latency plus equality/GIN query execution times. The test uses deterministic embeddings to isolate identity behavior. It does not validate the production embedding model or the final response of a live language model.

In the dashboard checkout:

```sh
npm test -- src/components/ai/KnowledgeSearchResults.test.tsx src/lib/knowledge-search.test.ts
npm run build
```

## Pilot rollout, 2026-09-05

Reviewed backend commit `04ef55f` and dashboard commit `272889c` were deployed through TeamCity run 8350 (#247). All six pipeline jobs succeeded. The deployed identity and assistant-integration file hashes matched the reviewed backend snapshot. Migration `e1c7a4b9d620` follows the already-deployed `49703b66f5d6` migration.

For guild `478278763239702538`, all nine linked accounts were refreshed successfully from Discord and 1,269 retained memberships were reconciled. The linked-account audit reports zero missing memberships, usernames, or aliases. Before refresh, one linked membership and one username were missing. No KB text or embeddings were changed.

Production read-only checks resolved all nine linked usernames. Shared retrieval using the real embedding service returned the intended sources for `studiocolors` and `aronz`; the latter was retrieved by the identity branch alone. Neither query reported a degraded component. The pilot flag is now recorded in the deployment ConfigMap for API and bot activation. Final Discord answer quality remains for the user's real-world check. The release note remains an unpublished, non-public draft pending that check.

Review validation: 25 identity/isolation tests passed (the optional scale benchmark was skipped); 91 other focused regressions passed; all three release-note tests passed. The identity fixture now uses the real Alembic migration chain, and release-history assertions account for the previously deployed YouTube fix. Dashboard: five tests and production build passed. Single Alembic head, offline migration rendering, and diff whitespace checks passed.
