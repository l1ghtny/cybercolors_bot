# Container registry maintenance

The internal registry uses `registry-claim-longhorn-v2`, a 200 GiB volume on the
dedicated `longhorn-registry` StorageClass. It has two replicas and
`best-effort` data locality so one replica remains beside the registry pod on
`new-node` while a second replica on `k8s-node-2` provides node-level
resilience. The original 100 GiB claim is retained as a migration rollback.

Apply the versioned storage request and maintenance resources with:

```sh
kubectl apply -k deploy/k8s/container-registry
```

`registry-retention` runs Sundays at 03:00 Europe/Bratislava. It protects
`latest` and the highest numeric indexer tag. Other aliases (including an
`idx-*` tag) remain protected when they point at the same live manifest;
manifests referenced only by older tags are deleted through the registry API.

`registry-garbage-collection` runs at 03:30. It scales the registry down,
mounts the same PVC in a one-shot `registry:2.8.1` job, removes unreferenced
blobs and untagged manifests, trims the freed blocks back to Longhorn, and
restores the registry even if collection fails.

The StorageClass applies the replica policy to replacement volumes. For the
pre-migration volume, the equivalent one-time settings were:

```sh
kubectl -n longhorn-system patch volumes.longhorn.io \
  pvc-8d4e297c-b0b7-46ff-a710-02a7878af0f5 \
  --type merge \
  -p '{"spec":{"numberOfReplicas":2,"dataLocality":"best-effort","unmapMarkSnapChainRemoved":"enabled"}}'
```

`k8s-node-2` keeps a 20 GiB Longhorn disk reservation. The cluster-wide 25%
minimum-free-space guard remains unchanged; the smaller node-local reservation
allows the nominal 200 GiB replica to schedule while the registry's physical
footprint is kept small by weekly retention, GC, and trim.
