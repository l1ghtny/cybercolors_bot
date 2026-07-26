import os
import subprocess
import textwrap
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PIPELINE_PATH = ROOT / ".teamcity.cybercolors.yml"


def _migration_script() -> str:
    pipeline = PIPELINE_PATH.read_text()
    migration_job = pipeline.split("  run_migrations:\n", 1)[1].split(
        "\n  deploy:\n", 1
    )[0]
    script = migration_job.split("        script-content: |-\n", 1)[1]
    return textwrap.dedent(script)


def test_migration_script_is_valid_bash():
    result = subprocess.run(
        ["bash", "-n"],
        input=_migration_script(),
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_migration_wait_tolerates_creation_races_and_pending_containers():
    script = _migration_script()

    assert "for i in $(seq 1 600)" in script
    assert '.status.conditions[?(@.type=="Complete")].status' in script
    assert '.status.conditions[?(@.type=="Failed")].status' in script
    assert 'JOB_COMPLETE="${JOB_CONDITIONS%%|*}"' in script
    assert 'JOB_FAILED="${JOB_CONDITIONS#*|}"' in script
    assert "kubectl -n cybercolors wait" not in script
    assert "migration container has not started" in script
    assert 'kubectl -n cybercolors logs "$pod" -c migration' in script


def test_migration_script_survives_not_found_then_container_creation(tmp_path):
    fake_kubectl = tmp_path / "kubectl"
    state_path = tmp_path / "job-get-count"
    fake_kubectl.write_text(
        """#!/bin/bash
set -eu

if [[ "$*" == *" delete job "* ]]; then
  exit 0
fi
if [ "${1:-}" = "apply" ]; then
  cat >/dev/null
  exit 0
fi
if [[ "$*" == *" get job.batch/"* ]]; then
  count=0
  if [ -f "$FAKE_KUBECTL_STATE" ]; then
    count="$(<"$FAKE_KUBECTL_STATE")"
  fi
  count=$((count + 1))
  echo "$count" > "$FAKE_KUBECTL_STATE"
  if [ "$count" -eq 1 ]; then
    echo 'Error from server (NotFound): jobs.batch not found' >&2
    exit 1
  fi
  if [ "$count" -eq 2 ]; then
    printf '|'
    exit 0
  fi
  printf 'True|'
  exit 0
fi
if [[ "$*" == *" get pods "* && "$*" == *" -o name"* ]]; then
  echo 'pod/cybercolors-migration-test'
  exit 0
fi
if [[ "$*" == *" get pod/cybercolors-migration-test "* ]]; then
  printf '2026-07-26T12:00:00Z'
  exit 0
fi
if [[ "$*" == *" logs pod/cybercolors-migration-test "* ]]; then
  echo 'migration finished'
  exit 0
fi
exit 0
"""
    )
    fake_kubectl.chmod(0o755)
    env = os.environ | {
        "FAKE_KUBECTL_STATE": str(state_path),
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
    }

    result = subprocess.run(
        ["bash"],
        input=_migration_script(),
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert state_path.read_text().strip() == "3"
    assert "migration finished" in result.stdout
