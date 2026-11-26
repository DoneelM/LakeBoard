"""scripts/deploy_bundle.sh with a fake `databricks` CLI: no network, no workspace."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts/deploy_bundle.sh"

# What `bundle deploy` printed in the real failure (GitHub Actions, CLI 1.14.1), with the workspace host left out.
ALREADY_EXISTS = """Uploading bundle files to /Workspace/Users/***/.bundle/lakeboard/dev/files...
Error: cannot create resources.apps.portal: Failed to create app lakeboard-dev. An app with the same name already exists.

Endpoint: POST https://example.cloud.databricks.com/api/2.0/apps?no_compute=true
HTTP Status: 409 Conflict
API error_code: ALREADY_EXISTS
API message: Failed to create app lakeboard-dev. An app with the same name already exists.

Error: cannot create resources.apps.portal.permissions: dependency failed: resources.apps.portal
"""

# A fake CLI: records each call, and answers from files the test writes. The Nth `bundle deploy` prints
# deploy.N.out and exits with deploy.N.rc (0 when that file is missing).
FAKE = r"""#!/usr/bin/env bash
echo "$*" >> "$FAKE_DIR/calls"
case "$1 $2" in
  "bundle deploy")
    n=$(( $(cat "$FAKE_DIR/deploys" 2>/dev/null || echo 0) + 1 )); echo "$n" > "$FAKE_DIR/deploys"
    cat "$FAKE_DIR/deploy.$n.out" 2>/dev/null
    exit "$(cat "$FAKE_DIR/deploy.$n.rc" 2>/dev/null || echo 0)" ;;
  "bundle validate")
    echo '{"resources": {"apps": {"portal": {"name": "lakeboard-dev"}}}}' ;;
  "bundle deployment")
    exit "$(cat "$FAKE_DIR/bind.rc" 2>/dev/null || echo 0)" ;;
esac
"""


def deploy(tmp_path: Path, results: list[tuple[int, str]], bind_rc: int = 0):
    """Run the script with `bundle deploy` returning each (exit code, output) in turn. Returns (result, calls)."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    cli = bin_dir / "databricks"
    cli.write_text(FAKE, encoding="utf-8")
    cli.chmod(0o755)
    for n, (rc, out) in enumerate(results, start=1):
        (tmp_path / f"deploy.{n}.rc").write_text(str(rc))
        (tmp_path / f"deploy.{n}.out").write_text(out)
    (tmp_path / "bind.rc").write_text(str(bind_rc))
    env = {"PATH": f"{bin_dir}{os.pathsep}{Path(sys.executable).parent}{os.pathsep}{os.environ['PATH']}",
           "FAKE_DIR": str(tmp_path)}
    r = subprocess.run(["bash", str(SCRIPT), "dev"], cwd=tmp_path, env=env, text=True, capture_output=True, check=False)
    calls = (tmp_path / "calls").read_text().splitlines() if (tmp_path / "calls").exists() else []
    return r, calls


def test_a_deploy_that_works_is_left_alone(tmp_path):
    r, calls = deploy(tmp_path, [(0, "Deployment complete!\n")])
    assert r.returncode == 0 and calls == ["bundle deploy -t dev"]
    assert "Deployment complete!" in r.stdout


def test_an_existing_app_is_bound_then_updated(tmp_path):
    r, calls = deploy(tmp_path, [(1, ALREADY_EXISTS), (0, "Deployment complete!\n")])
    assert r.returncode == 0
    assert calls == ["bundle deploy -t dev",
                     "bundle validate -t dev -o json",
                     "bundle deployment bind portal lakeboard-dev -t dev --auto-approve",
                     "bundle deploy -t dev"]
    assert "ALREADY_EXISTS" in r.stdout   # the first failure stays visible in the log


@pytest.mark.parametrize("output", [
    "Error: cannot create resources.apps.portal: PERMISSION_DENIED\n",   # the app, but not a name clash
    "Error: cannot create resources.jobs.nightly: ALREADY_EXISTS\n",     # a name clash, but not the app
])
def test_any_other_failure_fails_without_binding(tmp_path, output):
    r, calls = deploy(tmp_path, [(1, output)])
    assert r.returncode == 1 and calls == ["bundle deploy -t dev"]


def test_the_original_exit_code_is_kept(tmp_path):
    r, _ = deploy(tmp_path, [(3, "Error: something else\n")])
    assert r.returncode == 3


def test_a_bind_that_fails_says_what_permission_is_missing(tmp_path):
    r, calls = deploy(tmp_path, [(1, ALREADY_EXISTS)], bind_rc=1)
    assert r.returncode == 1 and calls[-1].startswith("bundle deployment bind")
    assert calls.count("bundle deploy -t dev") == 1
    assert "CAN MANAGE" in r.stderr and "lakeboard-dev" in r.stderr


def test_a_second_deploy_that_fails_fails_the_step(tmp_path):
    r, calls = deploy(tmp_path, [(1, ALREADY_EXISTS), (1, "Error: still broken\n")])
    assert r.returncode == 1 and calls.count("bundle deploy -t dev") == 2


def test_both_pipelines_deploy_through_the_script():
    gh = (ROOT / ".github/workflows/deploy.yml").read_text(encoding="utf-8")
    ado = (ROOT / "pipelines/deploy-steps.yml").read_text(encoding="utf-8")
    assert 'bash scripts/deploy_bundle.sh "$TARGET"' in gh and "databricks bundle deploy" not in gh
    assert "bash scripts/deploy_bundle.sh ${{ parameters.target }}" in ado and "databricks bundle deploy" not in ado
