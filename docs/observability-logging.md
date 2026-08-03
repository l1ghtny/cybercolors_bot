# Persistent logging operations

The cluster runs two logging paths during migration:

- `loki-v2` + `alloy-logs` is the persistent path. Loki stores 30 days of logs on a 100 Gi Longhorn R2 PVC. Alloy runs on every node and sends Kubernetes pod logs to it.
- `loki` + `loki-promtail` is the legacy path. Keep it until the persistent path has completed a longer validation window, then remove it in a separate change.

The persistent pipeline deliberately drops the `replication-cert-copy` container. It continuously emits full Postgres pod status and previously accounted for almost half of cluster log volume. Application and Postgres server logs remain available.

## Open Grafana

Grafana has no public ingress. Open a local tunnel:

```bash
kubectl -n observability port-forward service/kube-prom-stack-grafana 3000:80
```

Then open `http://localhost:3000`. Under **Dashboards**, use:

- **CyberColors Logs** for the bot, backend, workers, and database logs in the `cybercolors` namespace.
- **Cluster Log Overview** for cross-namespace volume, errors, and the noisiest workloads.
- The chart-provided **Loki** dashboards for storage and query-engine internals.

The administrator username and password are stored in Kubernetes. Print them locally with:

```bash
kubectl -n observability get secret kube-prom-stack-grafana \
  -o jsonpath='{.data.admin-user}' | base64 -d; echo
kubectl -n observability get secret kube-prom-stack-grafana \
  -o jsonpath='{.data.admin-password}' | base64 -d; echo
```

## Reading the dashboards

1. Set the time range in the upper-right corner. Use **Last 15 minutes** for a live incident and **Last 6 hours** for background investigation.
2. On **CyberColors Logs**, narrow **Application** and **Container** before entering search text. An empty search shows every selected log line.
3. Drag across a graph to zoom into the spike. The log panels update to the same time window.
4. Expand a log row to inspect `pod`, `container`, `node_name`, and other labels. Those labels are usually more reliable than free-text search.
5. Use **Cluster Log Overview** when the source is unknown. Start with **Volume by namespace**, then use **Top applications by volume** to find the workload.
6. For an ad-hoc query, choose **Explore** in the left menu, select **Loki Persistent**, build a label selector, and add text filters last.

The dashboards are source-controlled and intentionally read-only. Make lasting changes in the JSON files under `deploy/k8s/observability/dashboards` and apply the Kustomization. Use **Save as** for temporary personal experiments.

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
helm upgrade --install loki-v2 grafana-community/loki \
  --namespace observability --version 18.7.1 \
  --values deploy/k8s/observability/loki-values.yaml \
  --wait --timeout 10m

helm upgrade --install alloy-logs grafana/alloy \
  --namespace observability --version 1.11.0 \
  --values deploy/k8s/observability/alloy-values.yaml \
  --wait --timeout 10m

kubectl apply -k deploy/k8s/observability
```

## Health and capacity checks

```bash
kubectl -n observability get pods,pvc -l app.kubernetes.io/instance=loki-v2
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

The legacy path remains untouched during validation. To stop new collection without deleting data, scale the Alloy DaemonSet to zero by uninstalling only `alloy-logs`; continue querying the legacy `Loki` datasource. Do not delete the `loki-v2` PVC. Reinstall Alloy after correcting its configuration.
