"""Publish one release to Argo, then observe it without rewriting workload images.

Concurrent releases use an optimistic lock on the Application. A superseded run
exits successfully; API errors and incomplete rollouts fail the deployment.
Only the Python standard library and kubectl are needed on a TeamCity agent.
"""

import argparse
import json
import re
import subprocess
import time


REGISTRY = "localhost:32000/"
APPLICATION = "cybercolors"
NAMESPACE = "cybercolors"
WORKERS = {
    "cybercolors-bot": "cybercolors-backend",
    "modral-bot": "cybercolors-backend",
    "cybercolors-newcomer-release-worker": "cybercolors-backend",
    "cybercolors-scheduled-posts-worker": "cybercolors-backend",
    "cybercolors-privacy-retention-worker": "cybercolors-backend",
    "cybercolors-indexer-worker": "cybercolors-indexer",
    "cybercolors-youtube-channel-worker": "cybercolors-indexer",
    "cybercolors-embeddings": "cybercolors-embeddings",
}


class Superseded(Exception):
    pass


class Kubectl:
    def get(self, namespace, kind, name):
        result = subprocess.run(
            ["kubectl", "-n", namespace, "get", kind, name, "-o", "json"],
            check=True, capture_output=True, text=True,
        )
        return json.loads(result.stdout)

    def patch(self, namespace, kind, name, operations, *, status=False):
        command = ["kubectl", "-n", namespace, "patch", kind, name, "--type=json",
                   "-p", json.dumps(operations)]
        if status:
            command.append("--subresource=status")
        subprocess.run(command, check=True, capture_output=True, text=True)


def images(application):
    values = application.get("spec", {}).get("source", {}).get("kustomize", {}).get("images", [])
    return {value.rsplit(":", 1)[0]: value for value in values}


def image_tags(application):
    return {name.removeprefix(REGISTRY): value.rsplit(":", 1)[1]
            for name, value in images(application).items()}


def check_monotonic(current, desired):
    for name in ("cybercolors-backend", "cybercolors-frontend"):
        old = current.get(name)
        if old is not None and not old.isdecimal():
            raise ValueError(f"Cannot order existing {name} tag {old!r}; refusing an automatic overwrite")
        if old is not None and int(old) > int(desired[name]):
            raise Superseded(f"{name}:{old} is newer than requested {desired[name]}")


def publish(kube, desired):
    """One atomic image update; retry only when the observed version changed."""
    for _ in range(10):
        app = kube.get("argocd", "application", APPLICATION)
        current = image_tags(app)
        check_monotonic(current, desired)
        if all(current.get(name) == tag for name, tag in desired.items()):
            return
        # The same numbered builds must not be paired with different source hashes.
        if all(current.get(name) == desired[name] for name in
               ("cybercolors-backend", "cybercolors-frontend")):
            raise ValueError("Identical build numbers have different worker image hashes")
        merged = images(app) | {REGISTRY + name: REGISTRY + name + ":" + tag
                                for name, tag in desired.items()}
        version = app["metadata"]["resourceVersion"]
        operations = [{"op": "test", "path": "/metadata/resourceVersion", "value": version}]
        if "kustomize" not in app["spec"]["source"]:
            operations.append({"op": "add", "path": "/spec/source/kustomize", "value": {}})
        operations.append({"op": "add", "path": "/spec/source/kustomize/images",
                           "value": list(merged.values())})
        try:
            kube.patch("argocd", "application", APPLICATION, operations)
            print("Published release to Argo: " + json.dumps(desired, sort_keys=True), flush=True)
            return
        except subprocess.CalledProcessError:
            fresh = kube.get("argocd", "application", APPLICATION)
            if fresh["metadata"]["resourceVersion"] == version:
                raise
    raise RuntimeError("Application kept changing; no release was published")


def require_ownership(kube, desired):
    current = image_tags(kube.get("argocd", "application", APPLICATION))
    if any(current.get(name) != tag for name, tag in desired.items()):
        raise Superseded("Argo now targets another release; stopping without further mutations")


def has_image(resource, expected):
    return any(container.get("image") == expected for container in
               resource.get("spec", {}).get("template", {}).get("spec", {}).get("containers", []))


def deployment_ready(resource, expected):
    status = resource.get("status", {})
    count = resource["spec"].get("replicas", 1)
    return (has_image(resource, expected)
            and int(status.get("observedGeneration", 0)) >= resource["metadata"]["generation"]
            and status.get("updatedReplicas", 0) == count
            and status.get("availableReplicas", 0) >= count)


def rollout_ready(kube, name, expected, desired):
    workload = kube.get(NAMESPACE, "deployment", name)
    rollout = kube.get(NAMESPACE, "rollout", name)
    status = rollout.get("status", {})
    if rollout["spec"].get("paused"):
        raise RuntimeError(f"{name} was explicitly paused; refusing to override it")
    if status.get("phase") == "Degraded" or status.get("abort"):
        raise RuntimeError(f"{name} rollout failed: {status.get('message', status.get('phase'))}")
    if (not has_image(workload, expected)
            or str(status.get("workloadObservedGeneration")) != str(workload["metadata"]["generation"])
            or str(status.get("observedGeneration")) != str(rollout["metadata"]["generation"])):
        return False
    pod_hash = status.get("currentPodHash")
    if not pod_hash:
        return False
    replica_set = kube.get(NAMESPACE, "replicaset", f"{name}-{pod_hash}")
    if not has_image(replica_set, expected):
        return False
    count = rollout["spec"].get("replicas", 1)
    if (status.get("phase") == "Healthy" and status.get("stableRS") == pod_hash
            and status.get("updatedReplicas", 0) == count
            and status.get("availableReplicas", 0) >= count):
        return True
    if (status.get("phase") == "Paused" and not status.get("promoteFull")
            and replica_set.get("status", {}).get("availableReplicas", 0) > 0):
        require_ownership(kube, desired)
        # Equivalent to Argo's promote --full, but conditional on this exact
        # observed revision. A controller update or newer revision invalidates it.
        operations = [
            {"op": "test", "path": "/metadata/resourceVersion",
             "value": rollout["metadata"]["resourceVersion"]},
            {"op": "test", "path": "/status/currentPodHash", "value": pod_hash},
            {"op": "add", "path": "/status/promoteFull", "value": True},
        ]
        try:
            kube.patch(NAMESPACE, "rollout", name, operations, status=True)
            print(f"Promoted {name} revision {pod_hash}", flush=True)
        except subprocess.CalledProcessError:
            fresh = kube.get(NAMESPACE, "rollout", name)
            if fresh["metadata"]["resourceVersion"] == rollout["metadata"]["resourceVersion"]:
                raise
    return False


def deploy(kube, desired, *, timeout=1800, poll_seconds=5, clock=time.monotonic, sleep=time.sleep):
    try:
        publish(kube, desired)
        deadline = clock() + timeout
        previous = None
        while clock() < deadline:
            require_ownership(kube, desired)
            pending = []
            for name, image in WORKERS.items():
                resource = kube.get(NAMESPACE, "deployment", name)
                if not deployment_ready(resource, f"{REGISTRY}{image}:{desired[image]}"):
                    pending.append(name)
            # Wait for shared services before promoting application traffic.
            if not pending:
                for name in ("cybercolors-backend", "cybercolors-frontend"):
                    if not rollout_ready(kube, name, f"{REGISTRY}{name}:{desired[name]}", desired):
                        pending.append(name)
            if not pending:
                require_ownership(kube, desired)
                print("Release verified: all intended images and replicas are healthy", flush=True)
                return "completed"
            if pending != previous:
                print("Waiting for: " + ", ".join(pending), flush=True)
                previous = pending
            sleep(poll_seconds)
        raise TimeoutError("Release did not become healthy before the deployment timeout")
    except Superseded as exc:
        print(f"Superseded: {exc}", flush=True)
        return "superseded"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for component in ("backend", "frontend", "indexer", "embeddings"):
        parser.add_argument(f"--{component}-tag", required=True)
    args = parser.parse_args()
    desired = {f"cybercolors-{name}": getattr(args, f"{name}_tag")
               for name in ("backend", "frontend", "indexer", "embeddings")}
    for name, pattern in (("backend", r"[0-9]+"), ("frontend", r"[0-9]+"),
                          ("indexer", r"idx-[0-9a-f]{16}"), ("embeddings", r"emb-[0-9a-f]{16}")):
        if not re.fullmatch(pattern, desired[f"cybercolors-{name}"]):
            parser.error(f"Invalid {name} tag")
    try:
        deploy(Kubectl(), desired)
    except subprocess.CalledProcessError as exc:
        raise SystemExit(exc.stderr or str(exc)) from exc


if __name__ == "__main__":
    main()
