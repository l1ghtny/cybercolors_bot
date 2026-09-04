# Dependency updates and deployment

## YouTube downloader updates

`pyproject.toml` permits yt-dlp releases at or above the tested minimum. The
exact version and package hashes remain in `uv.lock`, and images install with
`uv sync --locked`. Removing the minimum version does not update an existing
image or a running worker.

Dependabot checks yt-dlp and yt-dlp-ejs on its daily schedule and groups their
updates into a pull request. The YouTube dependency workflow installs that
proposed lockfile and runs the downloader, URL, metadata, and transcription
adapter tests without production credentials. These are compatibility checks;
they do not prove that YouTube will accept a particular production proxy.

Review and merge a passing update PR, then follow the normal TeamCity release.
There is no automatic merge or package installation inside a running worker.
After a downloader update, retry a previously affected video and verify that
its source reaches `ready` with populated knowledge chunks.

For an urgent update:

```sh
uv lock --upgrade-package yt-dlp
uv sync --locked
```

## Concurrent deployments

`CyberColorsFlow` builds the images and runs migrations, then calls
`scripts/deploy_cybercolors.py`. The deployment script:

1. Reads the Argo Application and rejects releases older than either the
   deployed backend or frontend build number.
2. Publishes all four image overrides in one JSON patch, conditional on the
   Application resource version. A concurrent update must be reread before
   another publication attempt.
3. Lets Argo reconcile deployments. It never directly rewrites Deployment
   images or reapplies an old image list after waiting.
4. Stops if another release takes ownership of the Application.
5. Checks the expected image, observed generation, and updated availability
   for every worker. For backend/frontend it also checks the current ReplicaSet
   image and the Rollout's observed workload generation.
6. Promotes a ready paused canary using a patch conditional on the observed
   Rollout resource version and pod hash. Explicit manual pauses and failed
   rollouts fail the job rather than being overridden.

A duplicate run targeting the same images observes the existing rollout
without republishing it. A superseded run exits successfully and logs the
reason; API failures, permissions errors, and readiness timeouts fail the job.
An intentional rollback must use an explicit operator procedure, not replay an
older pipeline run.

The backend and frontend build numbers must identify the intended artifacts.
Worker image hashes must agree when both numbered builds are unchanged; a
mismatch is rejected instead of silently accepting a different checkout.

## TeamCity rollout observation permissions

`deploy/k8s/cybercolors/teamcity-rollout-observer.yaml` grants the
`gamedev/teamcity-metrics-deployer` service account `get`, `list`, and `watch`
on Deployments in the `cybercolors` namespace. Argo Rollouts' CLI uses a
namespace-wide informer, which cannot use the older resource-name-restricted
watch grant. Existing mutation permissions remain in their separate role.

After changing the pipeline YAML, validate and upload it to TeamCity; pushing
the repository alone does not update the pipeline definition:

```sh
teamcity pipeline validate .teamcity.cybercolors.yml
teamcity pipeline push CyberColors_CyberColorsFlow .teamcity.cybercolors.yml
```

Check for the VCS-triggered run before starting another run manually. Verify
Argo `Healthy`/`Synced`, the intended stable images, and ready replicas after
the release; a build result alone is not production verification.
