"""Regression checks for stale TeamCity snapshot dependency reuse."""
import os
from pathlib import Path
import subprocess

import pytest
import yaml

PIPELINE = yaml.safe_load(Path(".teamcity.cybercolors.yml").read_text())
SOURCE_JOBS = ("build_backend", "build_indexer", "build_embeddings", "run_migrations", "deploy")


@pytest.mark.parametrize("name", SOURCE_JOBS)
def test_backend_sources_are_tracked_and_never_cloned_from_moving_master(name):
    job = PIPELINE["jobs"][name]
    repositories = {key: value for entry in job["repositories"] for key, value in entry.items()}
    assert repositories["CyberColors_HttpsGithubComL1ghtnyCybercolorsBotGitRefsHeadsMaster2"] == {"enabled": True, "path": "cybercolors_bot"}
    script = job["steps"][0]["script-content"]
    assert "git clone" not in script
    assert "%build.vcs.number.CyberColors_HttpsGithubComL1ghtnyCybercolorsBotGitRefsHeadsMaster2%" in script
    assert subprocess.run(["bash", "-n"], input=script, text=True, capture_output=True).returncode == 0


def test_cluster_mutations_always_run_and_keep_migration_gate():
    assert PIPELINE["jobs"]["run_migrations"]["allow-reuse"] is False
    assert PIPELINE["jobs"]["deploy"]["allow-reuse"] is False
    assert "run_migrations" in PIPELINE["jobs"]["deploy"]["dependencies"]
    assert "build_backend" in PIPELINE["jobs"]["run_migrations"]["dependencies"]
    assert "org.opencontainers.image.revision=$ACTUAL_REVISION" in PIPELINE["jobs"]["build_backend"]["steps"][0]["script-content"]


@pytest.mark.parametrize("job, mismatch", [("deploy", "checkout"), ("deploy", "backend"),
                                         ("deploy", "indexer"), ("deploy", "embeddings"),
                                         ("run_migrations", "backend"), ("deploy", None)])
def test_revision_guards_refuse_mixed_source_releases(tmp_path, job, mismatch):
    repo = tmp_path / "cybercolors_bot"
    repo.mkdir()
    (repo / "main.py").touch()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                    "commit", "-q", "--allow-empty", "-m", "test"], check=True)
    revision = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    source = PIPELINE["jobs"][job]["steps"][0]["script-content"]
    start = source.index('CHECKOUT_DIR="')
    if job == "deploy":
        end = source.index('INDEXER_HASH=', start)
    else:
        end = source.index('ensure_kubectl()', start)
    script = "set -euo pipefail\n" + source[start:end]
    script = script.replace("%teamcity.build.checkoutDir%", str(tmp_path))
    script = script.replace("%build.vcs.number.CyberColors_HttpsGithubComL1ghtnyCybercolorsBotGitRefsHeadsMaster2%", "0" * 40 if mismatch == "checkout" else revision)
    for component in ["backend", "indexer", "embeddings"]:
        script = script.replace(f"%job.build_{component}.backend_revision%", "0" * 40 if mismatch == component else revision)
    result = subprocess.run(["bash"], input=script, text=True, capture_output=True)
    assert (result.returncode == 0) is (mismatch is None), result.stdout + result.stderr
