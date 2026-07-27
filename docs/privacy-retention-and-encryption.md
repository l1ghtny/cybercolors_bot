# Privacy retention and encryption baseline

This is the operational baseline for the CyberColors pilot. It describes the
implemented defaults, not a substitute for the public privacy policy or legal
review.

## Retention implemented by the worker

`src.workers.privacy_retention_worker` runs every 15 minutes in bounded batches.

| Data | Default | Cleanup behavior |
| --- | ---: | --- |
| Ordinary message content and attachment URLs | 30 days | Content is erased; per-message IDs, author/channel IDs, and timestamps remain for activity aggregates. |
| Deleted messages not linked to a moderation action | 30 days | Row is deleted. |
| Message or deleted-message evidence linked to an action | 365 days | Content and attachment metadata are erased; the action record and link remain. |
| Unlinked AI moderation decisions | 30 days | Row, input snapshot, and provider response are deleted. |
| AI decisions linked to a case/action | 365 days | Content, attachment metadata, explanations, and raw provider output are erased; outcome metadata remains. |
| AI answer request/response logs | 30 days | Row is deleted. |
| Monitored-user message/image/AI event content | 30 days | Content and attachment/jump metadata are erased. |
| Monitored-user event metadata | 90 days | Row is deleted. |
| Bot outbound-message audit | 90 days | Row is deleted. |
| Expired dashboard OAuth sessions | Session expiry | Row and encrypted Discord tokens are deleted. |

Environment variables can shorten or lengthen these defaults, but evidence
retention cannot be configured shorter than ordinary message-content retention.
The worker uses indexed age filters, `FOR UPDATE SKIP LOCKED`, and a configurable
batch size to avoid long locks on ingestion and dashboard queries.

Backups can still contain data removed from the live database until pgBackRest
expires the backup set. The current schedule retains four weekly full backups
and fourteen differential backups.

## Encryption status (2026-07-27)

- Dashboard OAuth tokens are encrypted at the application layer with Fernet.
- PostgreSQL backups are encrypted client-side by pgBackRest with
  `aes-256-cbc` before upload to R2. The passphrase is stored in the Kubernetes
  Secret `cybercolors-db-pgbackrest-secrets`, not in Git.
- R2 also encrypts all objects and object metadata at rest with provider-managed
  AES-256 encryption.
- PostgreSQL enforces `hostssl` with SCRAM for application clients and
  certificate authentication for replication. All 16 observed application
  connections and both replication connections used TLS.
- The three live PostgreSQL data PVCs currently use `microk8s-hostpath`.
  Kubernetes manifests do not prove that the underlying node filesystems are
  encrypted, so live database files must be treated as unencrypted at rest
  until host disk encryption is verified or the cluster is migrated.

## Live database encryption decision

PostgreSQL 18 does not provide transparent encryption for the whole database in
core. Encrypting individual text columns would break ordinary text inspection,
search, moderation queries, and operational troubleshooting while leaving WAL,
indexes, temporary files, and other personal fields to handle separately.

Use block-volume encryption instead. The current preferred candidate is a
Longhorn StorageClass with `encrypted: "true"` and a Kubernetes-held LUKS key,
with one Longhorn replica per PVC because PostgreSQL already maintains three
database replicas. Do not change the StorageClass of existing PVCs in place;
create a replacement cluster/volumes and restore or clone into them.

The live database is 97 MB. A two-second AES-256-XTS microbenchmark on one
PostgreSQL replica measured about 12 GB/s at 1 KiB blocks, so cipher CPU is not
expected to be the bottleneck. The material performance risk is Longhorn/CSI
latency compared with local hostpath storage, plus the operational risk of the
volume migration.

Before cutover:

1. Confirm `dm_crypt` and `cryptsetup` on every eligible node and back up the
   volume key outside the cluster.
2. Create an encrypted staging StorageClass and a disposable PostgreSQL clone.
3. Run the same `pgbench` workload against hostpath and encrypted storage;
   compare TPS, p95 latency, WAL write latency, CPU, and failover recovery.
4. Accept only if p95 write latency is within 15% and there are no readiness or
   failover regressions under the expected pilot load.
5. Take and verify a fresh encrypted pgBackRest backup, rehearse restore, then
   migrate one replica at a time or cut over to a replacement PGO cluster with
   a documented rollback point.

## Remaining work before a commercial launch

- Add a public privacy policy and an in-product/user-accessible data deletion
  request path.
- Add per-guild controls for content storage, AI processing, attachment
  processing, deleted-message evidence, and retention windows.
- Define closed moderation-case retention and delete expired R2 evidence
  objects and abandoned uploads; case attachments are not yet cleaned by the
  database retention worker.
- Verify host access, Kubernetes Secret encryption at rest, audit logs, and
  incident-response ownership.
- Document OpenAI and Cloudflare as subprocessors, data locations/transfers,
  support access, breach handling, and the backup-deletion lag.
- Add deletion/anonymisation workflows for users and guilds that remove the bot.
