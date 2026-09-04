import copy
import subprocess

import pytest

from scripts import deploy_cybercolors as release


DESIRED = {
    "cybercolors-backend": "100",
    "cybercolors-frontend": "200",
    "cybercolors-indexer": "idx-" + "a" * 16,
    "cybercolors-embeddings": "emb-" + "b" * 16,
}


def application(tags, version="1"):
    return {"metadata": {"resourceVersion": version}, "spec": {"source": {"kustomize": {
        "images": [f"{release.REGISTRY}{name}:{tag}" for name, tag in tags.items()]
    }}}}


def workload(image, *, available=2):
    return {"metadata": {"generation": 7},
            "spec": {"replicas": 2, "template": {"spec": {"containers": [{"image": image}]}}},
            "status": {"observedGeneration": 7, "updatedReplicas": 2,
                       "availableReplicas": available}}


class FakeKube:
    def __init__(self, tags=None):
        self.app = application(tags or (DESIRED | {"cybercolors-backend": "99"}))
        self.patches = []
        self.before_patch = None
        self.not_ready = False
        self.rollout = {
            "metadata": {"resourceVersion": "10", "generation": 4},
            "spec": {"replicas": 2},
            "status": {"observedGeneration": "4", "workloadObservedGeneration": "7",
                       "phase": "Healthy", "currentPodHash": "new", "stableRS": "new",
                       "updatedReplicas": 2, "availableReplicas": 2},
        }

    def get(self, namespace, kind, name):
        if kind == "application":
            return copy.deepcopy(self.app)
        if kind == "rollout":
            return copy.deepcopy(self.rollout)
        component = name.removesuffix("-new") if kind == "replicaset" else release.WORKERS.get(name, name)
        return workload(f"{release.REGISTRY}{component}:{DESIRED[component]}",
                        available=0 if self.not_ready else 2)

    def patch(self, namespace, kind, name, operations, *, status=False):
        if self.before_patch:
            hook, self.before_patch = self.before_patch, None
            hook(self)
        resource = self.app if kind == "application" else self.rollout
        for op in operations:
            if op["op"] == "test":
                value = resource
                for key in op["path"].strip("/").split("/"):
                    value = value[key]
                if value != op["value"]:
                    raise subprocess.CalledProcessError(1, ["kubectl"], stderr="test failed")
        self.patches.append((kind, copy.deepcopy(operations), status))
        for op in operations:
            if op["op"] == "add":
                keys = op["path"].strip("/").split("/")
                target = resource
                for key in keys[:-1]:
                    target = target[key]
                target[keys[-1]] = op["value"]
        resource["metadata"]["resourceVersion"] = str(int(resource["metadata"]["resourceVersion"]) + 1)


def test_success_publishes_once_and_never_writes_deployment_images():
    kube = FakeKube()
    assert release.deploy(kube, DESIRED) == "completed"
    assert [kind for kind, _, _ in kube.patches] == ["application"]
    assert release.image_tags(kube.app) == DESIRED


@pytest.mark.parametrize("component", ["cybercolors-backend", "cybercolors-frontend"])
def test_older_backend_or_frontend_cannot_overwrite_newer_release(component):
    kube = FakeKube(DESIRED | {component: str(int(DESIRED[component]) + 1)})
    assert release.deploy(kube, DESIRED) == "superseded"
    assert kube.patches == []


def test_compare_and_swap_loses_to_newer_release_without_overwriting_it():
    kube = FakeKube()
    newer = DESIRED | {"cybercolors-backend": "101"}
    kube.before_patch = lambda k: setattr(k, "app", application(newer, "2"))
    assert release.deploy(kube, DESIRED) == "superseded"
    assert release.image_tags(kube.app) == newer
    assert kube.patches == []


def test_unrelated_resource_version_change_is_retried_without_losing_other_images():
    kube = FakeKube()
    extra = "example.local/other:12"
    def modify(k):
        k.app["metadata"]["resourceVersion"] = "2"
        k.app["spec"]["source"]["kustomize"]["images"].append(extra)
    kube.before_patch = modify
    assert release.deploy(kube, DESIRED) == "completed"
    assert extra in kube.app["spec"]["source"]["kustomize"]["images"]


def test_duplicate_release_observes_existing_work_without_republishing():
    kube = FakeKube(DESIRED)
    assert release.deploy(kube, DESIRED) == "completed"
    assert kube.patches == []


def test_superseded_during_long_worker_wait_never_reapplies_old_images():
    kube = FakeKube()
    kube.not_ready = True
    def newer_release(_seconds):
        kube.app = application(DESIRED | {"cybercolors-backend": "101"}, "3")
    assert release.deploy(kube, DESIRED, sleep=newer_release) == "superseded"
    assert len(kube.patches) == 1
    assert release.image_tags(kube.app)["cybercolors-backend"] == "101"


def test_api_permission_failure_is_not_treated_as_supersession_or_success():
    kube = FakeKube()
    def forbidden(_kube):
        raise subprocess.CalledProcessError(1, ["kubectl"], stderr="Forbidden")
    kube.before_patch = forbidden
    with pytest.raises(subprocess.CalledProcessError, match="non-zero"):
        release.deploy(kube, DESIRED)
    assert kube.patches == []


def test_changed_worker_hash_for_same_numbered_builds_fails_closed():
    kube = FakeKube(DESIRED | {"cybercolors-indexer": "idx-" + "c" * 16})
    with pytest.raises(ValueError, match="different worker image hashes"):
        release.deploy(kube, DESIRED)
    assert kube.patches == []


def test_health_from_previous_deployment_generation_is_not_success():
    item = workload("test:1")
    item["status"]["observedGeneration"] = 6
    assert not release.deployment_ready(item, "test:1")
    item["status"]["observedGeneration"] = 7
    assert not release.deployment_ready(item, "test:2")
    assert release.deployment_ready(item, "test:1")


def test_old_healthy_rollout_does_not_count_as_new_workload_ready():
    kube = FakeKube(DESIRED)
    kube.rollout["status"]["workloadObservedGeneration"] = "6"
    assert not release.rollout_ready(kube, "cybercolors-backend", "localhost:32000/cybercolors-backend:100", DESIRED)
    assert kube.patches == []


def test_pause_promotion_is_conditional_on_exact_ready_revision():
    kube = FakeKube(DESIRED)
    kube.rollout["status"].update(phase="Paused", stableRS="old")
    assert not release.rollout_ready(kube, "cybercolors-backend", "localhost:32000/cybercolors-backend:100", DESIRED)
    assert kube.rollout["status"]["promoteFull"] is True
    kind, operations, status = kube.patches[0]
    assert kind == "rollout" and status
    assert operations[:2] == [
        {"op": "test", "path": "/metadata/resourceVersion", "value": "10"},
        {"op": "test", "path": "/status/currentPodHash", "value": "new"},
    ]


def test_revision_changed_before_promotion_is_not_promoted():
    kube = FakeKube(DESIRED)
    kube.rollout["status"].update(phase="Paused", stableRS="old")
    def change_revision(k):
        k.rollout["metadata"]["resourceVersion"] = "11"
        k.rollout["status"]["currentPodHash"] = "another"
    kube.before_patch = change_revision
    assert not release.rollout_ready(kube, "cybercolors-backend", "localhost:32000/cybercolors-backend:100", DESIRED)
    assert kube.patches == []


@pytest.mark.parametrize("replicas,weight,promoted", [(0, 0, True), (1, 0, False), (0, 5, False)])
def test_zero_weight_pause_can_promote_without_canary_pods(replicas, weight, promoted):
    kube = FakeKube(DESIRED)
    kube.rollout["status"].update(phase="Paused", stableRS="old",
                                  canary={"weights": {"canary": {"weight": weight}}})
    original_get = kube.get
    def get(namespace, kind, name):
        resource = original_get(namespace, kind, name)
        if kind == "replicaset":
            resource["spec"]["replicas"] = replicas
            resource["status"]["availableReplicas"] = 0
        return resource
    kube.get = get
    assert not release.rollout_ready(kube, "cybercolors-backend", "localhost:32000/cybercolors-backend:100", DESIRED)
    assert bool(kube.patches) is promoted


@pytest.mark.parametrize("state", ["manual_pause", "degraded"])
def test_manual_pause_and_failed_rollout_are_not_bypassed(state):
    kube = FakeKube(DESIRED)
    if state == "manual_pause":
        kube.rollout["spec"]["paused"] = True
    else:
        kube.rollout["status"]["phase"] = "Degraded"
    with pytest.raises(RuntimeError):
        release.deploy(kube, DESIRED)
    assert kube.patches == []


def test_incomplete_release_times_out_instead_of_reporting_success():
    kube = FakeKube()
    kube.not_ready = True
    elapsed = [0]
    def advance(seconds):
        elapsed[0] += seconds
    with pytest.raises(TimeoutError):
        release.deploy(kube, DESIRED, timeout=10, clock=lambda: elapsed[0], sleep=advance)
    assert len(kube.patches) == 1
