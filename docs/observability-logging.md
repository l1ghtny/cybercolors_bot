# Persistent logging operations

The cluster runs one logging path: `loki-v2` + `alloy-logs`. Loki stores 30
days of logs on a retained 100 Gi Longhorn R2 PVC. Alloy runs on every node and
sends Kubernetes pod logs to it. The ephemeral Loki/Promtail release was retired
on 2026-08-03 after ingestion and restart-durability checks passed.

The persistent pipeline deliberately drops the `replication-cert-copy` container. It continuously emits full Postgres pod status and previously accounted for almost half of cluster log volume. Application and Postgres server logs remain available.

## Open Grafana

The primary browser entry point is `https://observability.lightny.pro`. It is
published through the `inside_main_kuber_node` Cloudflare Tunnel and protected
by an owners-only Cloudflare Access policy. The legacy `graphana.lightny.pro`
and `prometheus.lightny.pro` aliases are covered by the same Access application
so they cannot bypass authentication.

For emergency access that does not depend on Cloudflare, open a local tunnel:

```bash
kubectl -n observability port-forward service/kube-prom-stack-grafana 3000:80
```

Then open `http://localhost:3000`. Under **Dashboards**, use:

- **CyberColors Logs** for the bot, backend, workers, and database logs in the `cybercolors` namespace.
- **Cluster Log Overview** for cross-namespace volume, errors, and the noisiest workloads.
- **Platform Overview** for node health, cluster CPU and memory, filesystem and PVC capacity, scrape health, alerts, and restart offenders.
- **CyberColors Runtime** for pod readiness, PostgreSQL availability, per-pod CPU, memory, throttling, network throughput, and storage.
- **Observability Health** for Prometheus ingestion and rules, Loki ingestion and canary latency, Alloy configuration health, targets, alerts, and observability PVCs.
- The chart-provided **Loki** dashboards for storage and query-engine internals.

The persistent Grafana database preserves the login that was in use before the
upgrade. The Kubernetes admin secret is bootstrap configuration and may not
match a password that was changed in Grafana. Do not reset the administrator
password merely to make it match the secret.

## Reading the dashboards

1. Set the time range in the upper-right corner. Use **Last 15 minutes** for a live incident and **Last 6 hours** for background investigation.
2. On **CyberColors Logs**, narrow **Application** and **Container** before entering search text. An empty search shows every selected log line.
3. Drag across a graph to zoom into the spike. The log panels update to the same time window.
4. Expand a log row to inspect `pod`, `container`, `node_name`, and other labels. Those labels are usually more reliable than free-text search.
5. Use **Cluster Log Overview** when the source is unknown. Start with **Volume by namespace**, then use **Top applications by volume** to find the workload.
6. For an ad-hoc query, choose **Explore** in the left menu, select **Loki Persistent**, build a label selector, and add text filters last.

The dashboards are source-controlled and intentionally read-only. Make lasting changes in the JSON files under `deploy/k8s/observability/dashboards` and apply the Kustomization. Use **Save as** for temporary personal experiments.

The CyberColors dashboard currently measures workload-level performance. HTTP
request latency, Discord event latency, queue depth, and business-operation
rates require application metrics that the services do not expose yet. Sentry
continues to provide application error tracing; add OpenTelemetry or native
Prometheus instrumentation before treating Grafana as an application APM.

## Grafana MCP for ChatGPT

The read-only remote MCP endpoint is:

```text
https://grafana-mcp.lightny.pro/mcp
```

It is intentionally separate from the Grafana UI hostname. Cloudflare Access
Managed OAuth authenticates the MCP client, and an Envoy sidecar validates the
resulting Access JWT against the application audience before forwarding traffic
to `mcp-grafana`. The MCP server then authenticates to Grafana through the
`chatgpt-grafana-mcp` service account token stored in the
`grafana-mcp-credentials` Kubernetes Secret.

The server exposes observability query tools plus dashboard creation and editing.
Other write-capable categories, including alert-rule management and folder
creation, are excluded from `--enabled-tools`. To connect it in ChatGPT, enable
Developer mode and create an app with the URL above and OAuth authentication.
Never paste the Grafana service account token into ChatGPT.

The Cloudflare Access application's Managed OAuth DCR allowlist must include
`https://chatgpt.com/connector/oauth/*` so ChatGPT's per-app callback URL can be
registered without allowing unrelated ChatGPT paths.

Keep **Binding Cookie** disabled on this Access application. Cloudflare does not
support that browser-cookie control for non-browser clients; enabling it breaks
ChatGPT after OAuth approval. The owner-only Access policy and Envoy's Access
JWT issuer/audience validation remain the authorization boundary.

The token Secret is deliberately not source-controlled. If it must be rotated,
create a new token for the existing Grafana service account, update the Secret,
restart `deployment/grafana-mcp`, verify a real MCP query, and then revoke the
old token.

In **Explore**, select the **Loki Persistent** datasource. Start with the label browser, then narrow results before searching text.

## Useful LogQL queries

All CyberColors logs:

```logql
{namespace="cybercolors"}
```

Errors while excluding expected health checks:

```logql
{namespace="cybercolors"} |~ "(?i)(error|exception|traceback|critical)" != "/healthz"
```

One pod or container:

```logql
{namespace="cybercolors", pod=~"cybercolors-backend-.*", container="backend"}
```

Volume by application over five minutes:

```logql
sum by (app) (count_over_time({namespace="cybercolors"}[5m]))
```

Search for a Discord user or guild ID:

```logql
{namespace="cybercolors"} |= "liquidus0550"
```

Use exact IDs where possible. Usernames may change and are not present on every log line.

## Deploy or upgrade

Chart versions are pinned so changes are reproducible:

```bash
kubectl apply -k deploy/k8s/observability

helm upgrade --install kube-prom-stack \
  prometheus-community/kube-prometheus-stack \
  --namespace observability --version 88.1.3 \
  --values deploy/k8s/observability/kube-prometheus-stack-values.yaml \
  --wait --timeout 15m

helm upgrade --install loki-v2 grafana-community/loki \
  --namespace observability --version 18.7.1 \
  --values deploy/k8s/observability/loki-values.yaml \
  --wait --timeout 10m

helm upgrade --install alloy-logs grafana/alloy \
  --namespace observability --version 1.11.0 \
  --values deploy/k8s/observability/alloy-values.yaml \
  --wait --timeout 10m
```

The monitoring-stack upgrade job applies the Prometheus Operator CRDs before
the operator starts. Prometheus retains up to 30 days or 40 GB on a retained
50 Gi Longhorn R2 volume. Grafana uses the separately managed `grafana-storage`
claim, and Alertmanager uses a retained 2 Gi claim.

Grafana 13 uses the current chart, while its Kubernetes sidecars remain pinned
to `1.22.0`. The newer sidecar runtime rejects the older MicroK8s
service-account CA. This pin keeps certificate verification enabled; remove it
after rotating that CA with modern key-usage extensions. Sidecars write watched
ConfigMaps to disk without admin reload requests so the existing Grafana login
remains untouched. Dashboard files are polled automatically. After changing a
datasource ConfigMap, restart the Grafana deployment to load it.

The 2026-08-03 migration retained an untouched v9 database at
`/var/lib/grafana/preupgrade-v9/grafana.db`. The old empty `playlist` table also
required `created_at` and `updated_at` integer columns before Grafana 13's
unified-storage migration could start.

## Health and capacity checks

```bash
kubectl -n observability get pods,pvc -l app.kubernetes.io/instance=loki-v2
kubectl -n observability get pvc
kubectl -n observability get daemonset alloy-logs
kubectl -n observability logs daemonset/alloy-logs --container alloy --tail=100
kubectl -n observability port-forward service/loki-v2-gateway 3101:80
curl -fsS http://localhost:3101/ready
```

The PVC is retained if the Loki StatefulSet or Helm release is deleted. Retention removes log data older than 30 days; it does not resize the PVC. Watch actual use and expand the claim before it approaches 80%.

## Alerts

The Loki chart provisions Prometheus alert rules and dashboards. The current cluster Alertmanager receiver is intentionally null, so these rules are visible in Grafana/Prometheus but do not send Slack messages yet. Sentry's Slack integration covers application errors; infrastructure alerts need a separate Alertmanager Slack webhook or another receiver.

Open **Alerting → Alert rules** in Grafana and filter for `loki`. A healthy rule can be normal, pending, or firing; a rule with an evaluation error needs immediate attention. The most useful first signals are request errors, discarded samples, and canary latency/failures.

## Rollback

The retired `loki` and `tempo` Helm histories were retained, but their workloads
must not be restored unless an incident proves a current dependency. The old
Loki data lived on `emptyDir` and is not a durable rollback target.

To stop new log collection without deleting stored data, uninstall only
`alloy-logs`. Do not delete `storage-loki-v2-0`; reinstall Alloy after correcting
its configuration.

Do not roll Grafana back from 13 to 9 against the migrated database. A Grafana 9
rollback requires stopping Grafana and restoring the retained
`preupgrade-v9/grafana.db` first. Back up the current database before attempting
that recovery.
