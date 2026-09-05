# Search linked Discord identities alongside KB content

Status: approved design, implemented locally on 2026-09-04. The query examples below explain the design; the implementation and migration are authoritative. PostgreSQL integration checks pass in a disposable schema. Production activation and end-to-end verification remain deployment steps; see [implementation evidence and rollout](ai-knowledge-identity-rollout.md).

## Intended behavior

A KB entry linked to a Discord account should be discoverable through that account's current username, global display name, and nickname in the relevant server. The administrator should be able to write the biography naturally without copying account identifiers into its text.

The acceptance example is the reported Denis Bailyn entry. Its body mentions Denis Bailyn, its linked account has the username `aronz`, and a search for `aronz` currently returns nothing. After this change, both `aronz` and `Who is aronz?` must retrieve the linked entry without editing or re-embedding it.

Use two logical indexes in the existing database:

| Index | Indexed material | Produces |
| --- | --- | --- |
| Content | Existing KB chunk embeddings | Passages relevant to the question |
| Identity | Current account names, with server and Discord ID | Candidate people and the name that matched |

The retrieval service joins identity candidates to eligible KB sources through `subject_user_id`, combines their passages with content-search results, and supplies identity evidence to the answer model. Each logical index can have several physical database indexes.

## Baseline findings before implementation

- `knowledge_source_index_text()` in `src/modules/ai/knowledge.py` embeds only the title and body.
- `search_server_knowledge()` queries chunk vectors and applies a minimum similarity score. It returns `subject_user_id` as metadata but does not search account names.
- `AIMain._append_relevant_knowledge()` separately loads public facts for the author and IDs extracted from expanded Discord mentions. `_knowledge_results_for_prompt()` identifies other subjects only by ID.
- `GlobalUser.username`, `GlobalUser.global_name`, and `User.server_nickname` already hold the canonical name fields. `AIKnowledgeSource.subject_user_id` already has a database index.
- `record_user_display_name_change()` can return before refreshing the account when the visible name stays the same, and it skips memberships with a server nickname. A username change can therefore be missed by this event path.
- The dashboard search result model requires numeric `score` and `distance`; `KnowledgeSearchCard` calls `score.toFixed(3)`.

These observations describe the starting checkout. Production name freshness and end-to-end retrieval latency have not been measured.

## Identity index schema

Add `ai_knowledge_identity_aliases`, a searchable projection of the canonical account and membership tables. Store one row per `(server_id, user_id, alias_kind)` for each nonempty current field.

| Column | Purpose |
| --- | --- |
| `server_id bigint` | Scope both nickname meaning and searches |
| `user_id bigint` | Stable Discord account ID |
| `alias_kind text` | Checked value: `username`, `global_name`, or `server_nickname` |
| `alias_text text` | Original name for display and match explanations |
| `normalized_alias text` | Case-normalized, NFC-normalized name with consistent whitespace |
| `search_vector tsvector` | Lexemes and positions generated from the normalized alias |
| `alias_phrase tsquery` | Phrase query generated from the same alias and configuration |
| `normalization_version integer` | Identifies the projection rules for future rebuilds |
| `indexed_at timestamptz` | When the projection changed; this is not a Discord freshness timestamp |

Use a composite foreign key to the server membership and cascade membership deletion. The composite primary key enforces one current value of each kind. Do not make names unique across people: Discord display names and server nicknames can collide.

Create a B-tree index on `(server_id, normalized_alias)` for complete-query equality, a B-tree index on `user_id` for account-wide updates, and a GIN index on `search_vector` for full-question retrieval. Verify the planner's handling of the server predicate at realistic scale. PostgreSQL recommends GIN for text search. [Index documentation](https://www.postgresql.org/docs/current/textsearch-indexes.html)

Populate aliases for all retained server memberships, including members without KB entries. Otherwise, a nickname shared by two people could look unique merely because only one has a biography. Membership presence remains available through the canonical table; a retained former member's last-known alias must not be presented as proof of current membership.

Keep the original spelling and punctuation. Normalization must not remove accents, transliterate names, or equate visually similar characters. Apply the same versioned normalization function to indexed aliases and queries. The first implementation must verify database encoding and collation compatibility.

Use PostgreSQL's `simple` text-search configuration with no stop-word list for the lexical representation. Names should not be stemmed or discarded because they are ordinary words. The configuration and normalization are fixed explicitly in schema functions rather than inherited from a connection default. [Dictionary behavior](https://www.postgresql.org/docs/current/textsearch-dictionaries.html)

## How a full question reaches the index

The input is the whole question. There is no preliminary function that guesses which substring is a person's name by scanning the member list.

1. Normalize the input and parse it once into a positional query document with `to_tsvector`.
2. Perform a complete-query equality lookup through `(server_id, normalized_alias)`.
3. Build an OR query from the query document's lexemes. Use a database helper that composes safely quoted lexemes as `tsquery` values; user input is always a bound parameter.
4. Search `search_vector` with that OR query through GIN. This generates alias candidates from any matching query term.
5. Recheck candidate aliases against the positional query document using their complete `alias_phrase`. Thus `Who is Denis Bailyn?` can match `Denis Bailyn`, while a query containing only `Denis` does not become a full-name match.
6. Retrieve all account IDs for the matched alias before deciding whether it is ambiguous. Perform this collision check across the server directory, before filtering for KB availability or applying the final result limit.

Using `plainto_tsquery` on the entire question directly against an alias would be wrong: it combines terms with AND, so an `aronz` alias would also have to contain `who` and `is`. The OR candidate search followed by a phrase recheck is deliberate. PostgreSQL supplies both phrase queries and query-composition operators. [Query parsing](https://www.postgresql.org/docs/current/textsearch-controls.html), [text-search operators](https://www.postgresql.org/docs/current/functions-textsearch.html)

Illustrative candidate query, with the normalization and OR-query helpers implemented separately:

```sql
SELECT a.server_id, a.user_id, a.alias_kind, a.alias_text
FROM ai_knowledge_identity_aliases AS a
WHERE a.server_id = :server_id
  AND a.search_vector @@ CAST(:any_query_terms AS tsquery)
  AND CAST(:query_document AS tsvector) @@ a.alias_phrase;
```

The first text predicate supports indexed candidate retrieval; the second validates the complete alias on those candidates. The equality branch is separate and remains available for aliases with no indexable lexemes.

Lexical equivalence is weaker than exact identifier equality. PostgreSQL's parser can treat punctuation specially. An alias such as `foo.bar` must not be promoted to an exact username match from `foo bar` or `foo`. A username match requires the complete handle spelling from the parser's token stream or complete-query equality. The initial SQL spike must validate dots, underscores, surrounding punctuation, Cyrillic, mixed scripts, and emoji using `ts_debug`. A phrase candidate whose punctuation cannot be verified remains weak evidence. [Parser documentation](https://www.postgresql.org/docs/current/textsearch-parsers.html)

Actual Discord mention IDs enter as structured targets from message metadata. Parsing the fixed `<@id>` syntax for the dashboard is a protocol operation, separate from natural-language identity search.

## Candidate meaning, ambiguity, and ranking

An index match establishes that a name occurs in the query. It does not establish that the user intended to discuss that person. In particular, a nickname such as `May`, `Art`, or `Свет` can also be ordinary text.

Represent match evidence explicitly:

| Evidence | Treatment |
| --- | --- |
| Discord mention or explicitly selected account ID | Direct target, subject to ordinary source eligibility |
| Complete-query exact alias | Strong identity candidate; check collisions |
| Full username or name phrase inside a question | Lexical identity candidate; retain how it matched |
| Partial alias, punctuation-only equivalence, or incomplete name | Weak candidate; cannot establish identity or bypass content relevance |
| Same unqualified alias belonging to multiple accounts | Ambiguous group; no automatic choice based on who has KB content |

For an explicit account-handle form, username evidence may disambiguate a display-name collision. For an unqualified alias, retain the collision. A short or common name inside prose must not receive a guaranteed top slot. The existing answer model receives conditional candidate context and asks for clarification when the referent is uncertain; identity search adds no separate LLM call.

Start with a transparent ranking policy rather than inventing a universal confidence score:

1. Retrieve up to 20 semantic candidates with the existing relevance threshold.
2. Retrieve complete identity matches, checking ambiguity before truncation. Start with a maximum of 100 admitted alias candidates and 8 distinct people. Overflow is reported as incomplete resolution, never treated as evidence of uniqueness. Query cost also needs a measured database timeout; an output limit alone does not bound work.
3. For each eligible, unambiguous identity candidate, retrieve up to 3 linked chunks, ordered by similarity within that person's sources. When semantic scoring is unavailable, use a deterministic source/ordinal order and label the fallback.
4. Order identity candidates by evidence class (direct target, complete-query equality, full username in prose, full name phrase), then matched phrase length, available within-subject semantic score, and stable user ID. Form the identity chunk list in rounds: the first chunk from each person, then the second, then the third. Direct targets and complete-query exact matches reserve one available result slot per target before general ranking. Within the remaining budget, fuse the ordered semantic and full-alias candidate lists with reciprocal rank fusion, initially `1 / (60 + rank)` per contributing list. Deduplicate by chunk ID, with source ID and chunk ordinal as final tie-breakers. These constants are starting values to evaluate, not measured optima.
5. Preserve the caller's total limit and avoid filling it with several chunks from one biography while omitting another explicit target. If the limit cannot represent all targets, expose truncation.

Identity-selected chunks may have a low semantic score; do not filter an exact account lookup back out through the semantic threshold. However, finding a person does not make every claim in their biography relevant to the question. Candidate metadata and answer instructions must preserve that distinction. A multi-chunk document should contribute its relevant passages, not automatically its first three chunks.

For ambiguous groups, return clarification metadata separately from answer-ready facts. A semantic hit tied to one of those accounts must not silently settle the ambiguity. The dashboard can offer account choices; the bot asks which member the user means when the answer depends on that choice. An incidental word match must not force a clarification question. Ordinary knowledge unrelated to that ambiguous group can still be used.

## One retrieval service and an explicit result contract

Introduce `retrieve_server_knowledge()` returning an internal envelope containing `items`, `identity_matches`, `ambiguities`, `truncated`, and `degraded_components`. Keep a list-returning compatibility wrapper where existing callers need one.

Add an optional `target_user_ids` list to the search request for an explicit account selection, bounded to 8 decimal-string Discord IDs. Validate server association and apply the same source eligibility as any other lookup; selecting an ID grants no permissions. An ambiguity entry contains the matched alias, candidate IDs with ordinary directory display labels, and an overflow flag. Candidate choices must respect the directory information available to the caller. A selection resubmits the original query with the chosen target ID and replaces the ambiguity for that alias only.

The shared service owns eligibility, both searches, subject expansion, deduplication, and ranking. Query-vector generation happens at most once. Do not run concurrent statements on the same SQLAlchemy `AsyncSession`; database operations stay sequential unless separate sessions are deliberately introduced.

Every branch applies the same requested server, visibility, ready status, deletion rules, and optional source-ID restrictions. Resolving an identity cannot broaden the caller's access. Alias records alone expose no KB facts.

Integrate the service with the dashboard search, the AI knowledge tool, and answer preloading. Pass author context and explicit mention targets separately: the author is background context, not automatically the subject of every question. Explicitly named targets take priority when the existing prompt budget is applied.

The current shared search function also serves moderation and source-scoped transcript searches. Give those callers an explicit semantic retrieval policy for the first release so this refactor does not silently change moderation context or transcript targeting. They still use the common eligibility code.

Extend each result with:

```text
retrieval_methods: [semantic | identity]
identity: {user_id, username, global_name, server_nickname} | null
identity_evidence: [{alias_kind, matched_alias, match_type}]
score: float | null       # Actual semantic similarity, when computed
distance: float | null    # Actual vector distance, when computed
```

Keep ranking scores internal. Do not set semantic similarity to `1.0` to represent an identity match. Update API models, frontend types, and nullable-score rendering together. Deploy tolerant frontend rendering before enabling responses that can contain null scores.

The dashboard shows a reason such as `Matched Discord username: aronz`, alongside semantic similarity when available. The AI prompt receives the same identity-to-fact association. It must distinguish an unambiguous match from a possible referent, and treat account names and KB text as data rather than instructions.

For parity tests, use the same query, source scope, and explicit targets in all entry points. The dashboard's plain search has no author background, so it should not claim to reproduce the bot's entire personalized prompt.

## Keeping the identity index current

Use database triggers to maintain the alias projection transactionally from canonical rows. There are already several writers, including Discord events, OAuth, imports, and profile hydration. Updating only one application helper would leave other writes uncovered.

- A `GlobalUser.username` or `global_name` change updates those alias kinds for all retained memberships of that user.
- Membership insertion creates its available alias rows. A server-nickname change replaces or removes only that alias kind. Membership deletion removes its aliases through the foreign key.
- Trigger conditions compare relevant fields with `IS DISTINCT FROM`. Unchanged profile writes do not rebuild aliases.
- Clearing a name removes its old alias. Superseded names are not retained implicitly as current identifiers, since usernames can be reassigned. Historical aliases would require a separate product decision.

Triggers keep the projection consistent with the database; they cannot make stale canonical Discord data current. Add an account-refresh path to `on_user_update` independent of nickname-history recording. It must persist username/global-name changes even when a server nickname masks them or the visible display name is unchanged. Preserve existing ownership checks for guild events.

Install projection maintenance before backfilling existing memberships. Make the backfill idempotent, batch it, and lock the canonical rows used by each batch while writing their aliases so an older snapshot cannot overwrite a newer rename. Use a documented lock order and retry deadlocks. Test the backfill against concurrent rename, nickname clearing, and membership deletion.

Build the initial projection from current stored names, then audit linked accounts for missing identity data and refresh them through the existing Discord directory path with bounded requests. Report missing data separately from indexing failures. A fresh alias `indexed_at` value does not prove the account was recently fetched from Discord.

The identity backfill does not queue KB embedding jobs. A rename changes identity rows while existing content vectors remain usable. Reconciliation can compare canonical fields with the derived projection and rebuild discrepancies after an interrupted maintenance operation.

## Failure behavior and rollout

If embedding generation fails, exact identity lookup can still return eligible linked chunks with null semantic scores and a degraded-search indicator. If identity lookup fails, return available semantic results and indicate the missing branch. Isolate recoverable database errors with a savepoint or separate transaction so one failed statement does not leave the session unusable. An empty search and an unavailable search are different outcomes.

Implementation order:

1. Run the isolated PostgreSQL analyzer/query spike and retrieval evaluation described below. Confirm the deployed PostgreSQL version and collation before choosing migration expressions.
2. Add the schema, normalization helpers, triggers, and backfill. Verify migration upgrade/downgrade and concurrent synchronization behavior in the test schema.
3. Add the retrieval envelope and nullable-score contract, then make the frontend tolerate it while identity retrieval remains disabled.
4. Integrate the shared retrieval service and structured identity context. Enable through one reversible rollout flag, initially for the pilot server after backfill and synchronization checks pass.
5. Verify the reported query through authenticated dashboard search and an actual Discord answer. Compare returned source IDs and final answer attribution. Database tests alone do not establish this result.

Rollback switches retrieval back to semantic mode and leaves the derived identity data available for diagnosis. Rolling back a feature flag does not require dropping tables or re-embedding content.

Before an implementation commit or push, apply the repository's release-note gate and its migration/test requirements. This document itself is a proposal, not a shipped product update.

## Work map

Paths in this table are relative to the named repository. New filenames are proposed.

| Repository / area | Work |
| --- | --- |
| `modral_bot`: `src/db/models.py`, new Alembic migration | Alias model, keys, physical indexes, functions, and triggers |
| `modral_bot`: new `scripts/backfill_knowledge_identities.py` | Idempotent backfill, reconciliation, and missing-data report |
| `modral_bot`: new `src/modules/ai/knowledge_identities.py` | Indexed candidate queries and match evidence |
| `modral_bot`: `src/modules/ai/knowledge.py` | Shared eligibility, candidate expansion, fusion, and degradation handling |
| `modral_bot`: `api/models/ai_knowledge.py`, `api/services/ai_knowledge.py` | Response envelope and search integration |
| `modral_bot`: `src/modules/ai/models.py`, `ai_main.py`, `tools.py`, chat input construction | Structured mention targets, identity context, tool response, explicit caller policies |
| `modral_bot`: `main.py`, profile persistence helpers, nickname-history integration | Refresh current account fields independently of historical-name recording |
| `bot-command-center`: `src/types/api.ts`, `src/pages/AIPage.tsx`, localization files | Match explanations, nullable scores, ambiguity selection, degraded-search state |

## Evaluation before enabling

Use a deterministic fixture with synthetic Discord IDs, a short synthetic biography under the example title, and an `aronz` alias absent from all KB text. Other fixtures should include duplicate names, an account without KB content, a former member, long multi-chunk sources, and restricted sources. Keep real user IDs and full biographies out of committed diagnostics. Compare against the actual reported entry only during the authorized runtime verification.

| Case | Required observation |
| --- | --- |
| `aronz`, `ARONZ`, `Who is aronz?`, `Что известно про aronz?` | Linked Denis entry appears; the body is unchanged |
| Current display name, server nickname, actual mention | Same linked source is discoverable, with the right evidence |
| Two named people in a comparison question | Both subjects represented within the declared budget |
| Username changes while display name stays fixed | New username works after canonical update; old current alias is removed |
| Global name changes while a server nickname is set | Canonical account and all relevant aliases refresh |
| Duplicate nickname, only one person has KB | Ambiguity remains; KB availability does not identify the person |
| Nickname is `May`, `Art`, or `Свет` in an unrelated question | No confident answer about that member merely because the word occurs |
| Dotted/underscored handles, emoji, Cyrillic, quotes and operators | Analyzer behavior recorded; no false exact-identifier claims or query syntax errors |
| `aronz123` or only part of a full name | No full-alias identity claim |
| Unrelated server, private visibility, disabled/deleted source, source restriction | Ineligible facts never enter results through identity expansion |
| Long biography with a relevant later chunk | Useful later passage selected rather than only opening chunks |
| Embedding failure, identity-query failure, candidate overflow | Explicit partial/truncated state; remaining valid branch usable |
| Existing content-only questions | Retrieval quality remains within the agreed baseline |
| Dashboard, AI tool, and answer preloading | Same eligible source IDs for equivalent inputs; correct attribution in the final answer |

Exercise actual PostgreSQL GIN, phrase, and vector operations for the retrieval tests. Mock-only tests cannot validate this design. Record `EXPLAIN (ANALYZE, BUFFERS)` for equality lookup, a selective handle in a sentence, and a common-name query, using both a pilot-sized fixture and a synthetic 100,000-member server. A sequential scan can be reasonable on a tiny table; the scale test must show that the design avoids an application-side member scan and unacceptable database work.

Measure recall at 5 for the identity cases, ambiguity handling, false identity promotion on negative questions, and added p50/p95 latency. Proposed acceptance: all deterministic identity/scope cases pass, no incorrect account attribution in the ambiguity and common-word fixtures, and added identity-search p95 stays below 100 ms on the declared test hardware. The latency target is provisional and excludes the existing embedding service; record hardware and corpus size with results.

The implemented analyzer preserves full-handle spelling after indexed candidate retrieval, and the deterministic fixtures cover common-word handling and ambiguity. The rollout document records measured lookup latency and separates fixture evidence from final-answer behavior that still needs runtime verification.
