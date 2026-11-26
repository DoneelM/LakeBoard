"""The deploy workflow's own shell: run its real steps with fake values, in a temp folder, with no network."""
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from portal import settings

ROOT = Path(__file__).resolve().parent.parent
STEPS = yaml.safe_load((ROOT / ".github/workflows/deploy.yml").read_text(encoding="utf-8"))["jobs"]["deploy"]["steps"]
HOST = "https://dbc-0123abcd-4567.cloud.databricks.com/"


def step(name: str) -> str:
    return next(s["run"] for s in STEPS if s.get("name") == name)


def run(name: str, tmp_path: Path, **env):
    out, summary, genv = tmp_path / "out", tmp_path / "summary", tmp_path / "env"
    base = {"PATH": f"{Path(sys.executable).parent}{os.pathsep}{os.environ['PATH']}", "TARGET": "dev",
            "GITHUB_OUTPUT": str(out), "GITHUB_STEP_SUMMARY": str(summary), "GITHUB_ENV": str(genv), "REPO": "DoneelM/LakeBoard", "BRANCH": "develop",
            "DATABRICKS_HOST": HOST, "DATABRICKS_WAREHOUSE_ID": "abc123def456", "HAS_CLIENT_ID": "true", "HAS_CLIENT_SECRET": "true"}
    base.update(env)
    r = subprocess.run(["bash", "-e", "-c", step(name)], cwd=tmp_path, env=base, text=True, capture_output=True, check=False)
    return r, out.read_text() if out.exists() else ""


CHECK = "Check this environment is set up"


def shown(r) -> str:
    """What the log shows: the runner consumes ::add-mask:: commands and never prints them."""
    return "".join(line for line in (r.stdout + r.stderr).splitlines(keepends=True) if not line.startswith("::add-mask::"))


def test_official_repo_with_all_four_values_is_ready(tmp_path):
    r, out = run(CHECK, tmp_path)
    assert r.returncode == 0 and "ready=true" in out


@pytest.mark.parametrize("env, named", [
    ({"DATABRICKS_HOST": ""}, ["DATABRICKS_HOST"]),
    ({"DATABRICKS_WAREHOUSE_ID": ""}, ["DATABRICKS_WAREHOUSE_ID"]),
    ({"HAS_CLIENT_ID": "false", "HAS_CLIENT_SECRET": "false"}, ["DATABRICKS_CLIENT_ID", "DATABRICKS_CLIENT_SECRET"]),
    ({"DATABRICKS_HOST": "", "DATABRICKS_WAREHOUSE_ID": "", "HAS_CLIENT_ID": "false", "HAS_CLIENT_SECRET": "false"},
     ["DATABRICKS_HOST", "DATABRICKS_WAREHOUSE_ID", "DATABRICKS_CLIENT_ID", "DATABRICKS_CLIENT_SECRET"]),
])
def test_official_repo_fails_naming_each_missing_key_and_no_values(tmp_path, env, named):
    r, out = run(CHECK, tmp_path, **env)
    error = next(line for line in r.stdout.splitlines() if line.startswith("::error::"))
    assert r.returncode == 1 and "ready=" not in out
    assert error.split(". Nothing")[0].split(": ")[-1].split() == named
    assert "dbc-0123abcd" not in shown(r) and "abc123def456" not in shown(r)


def test_the_host_reaches_later_steps_stripped_and_blank_counts_as_missing(tmp_path):
    r, _ = run(CHECK, tmp_path, DATABRICKS_HOST=f"  {HOST}\n")
    assert r.returncode == 0 and f"DATABRICKS_HOST={HOST}\n" in (tmp_path / "env").read_text()
    r, _ = run(CHECK, tmp_path, DATABRICKS_HOST="   ")
    assert r.returncode == 1 and "DATABRICKS_HOST" in r.stdout


def test_the_warehouse_id_reaches_later_steps_stripped_and_blank_counts_as_missing(tmp_path):
    r, _ = run(CHECK, tmp_path, DATABRICKS_WAREHOUSE_ID="  abc123def456\n")
    assert r.returncode == 0 and "DATABRICKS_WAREHOUSE_ID=abc123def456\n" in (tmp_path / "env").read_text()
    r, _ = run(CHECK, tmp_path, DATABRICKS_WAREHOUSE_ID="   ")
    assert r.returncode == 1 and "DATABRICKS_WAREHOUSE_ID" in r.stdout
    assert "abc123def456" not in r.stdout + r.stderr


@pytest.mark.parametrize("raw", [HOST, f"  {HOST}\n", "HTTPS://DBC-0123abcd-4567.cloud.databricks.com//"])
def test_the_host_is_masked_as_given_and_as_a_bare_host(tmp_path, raw):
    r, _ = run(CHECK, tmp_path, DATABRICKS_HOST=raw)
    masks = [line.removeprefix("::add-mask::") for line in r.stdout.splitlines() if line.startswith("::add-mask::")]
    assert r.returncode == 0 and raw.strip() in masks and "dbc-0123abcd-4567.cloud.databricks.com" in masks


def test_no_mask_for_a_missing_host(tmp_path):
    r, _ = run(CHECK, tmp_path, DATABRICKS_HOST="")
    assert "::add-mask::" not in r.stdout


def test_the_host_is_read_from_the_secret_first_then_the_variable():
    check = next(s for s in STEPS if s.get("name") == CHECK)
    assert check["env"]["DATABRICKS_HOST"] == "${{ secrets.DATABRICKS_HOST || vars.DATABRICKS_HOST }}"


def test_oidc_needs_no_client_secret(tmp_path):
    r, out = run(CHECK, tmp_path, HAS_CLIENT_SECRET="false", DATABRICKS_AUTH_TYPE="github-oidc")
    assert r.returncode == 0 and "ready=true" in out


def test_a_fork_with_a_host_still_deploys(tmp_path):
    r, out = run(CHECK, tmp_path, REPO="someone/LakeBoard", DATABRICKS_WAREHOUSE_ID="", HAS_CLIENT_SECRET="false")
    assert r.returncode == 0 and "ready=true" in out


def test_a_fork_without_a_host_skips_the_deploy(tmp_path):
    r, out = run(CHECK, tmp_path, REPO="someone/LakeBoard", DATABRICKS_HOST="")
    assert r.returncode == 0 and "ready=false" in out


def test_local_files_carry_the_workspace_and_the_app_matches_its_host(tmp_path, monkeypatch):
    (tmp_path / "src").mkdir()
    r, _ = run("Write the local workspace files", tmp_path)
    assert r.returncode == 0 and r.stdout == "" and r.stderr == ""
    bundle = yaml.safe_load((tmp_path / "databricks.local.yml").read_text())
    assert bundle == {"targets": {"dev": {"workspace": {"host": HOST}, "variables": {"warehouse_id": "abc123def456"}}}}
    cfg = yaml.safe_load((ROOT / "src/environments.yml").read_text(encoding="utf-8"))
    cfg = settings.with_local_hosts(cfg, tmp_path / "src/environments.local.yml")
    assert cfg["environments"]["dev"]["host"] == "dbc-0123abcd-4567.cloud.databricks.com"
    monkeypatch.setattr(settings, "ENVIRONMENTS", cfg["environments"])
    monkeypatch.delenv("PORTAL_ENV", raising=False)
    monkeypatch.setenv("DATABRICKS_HOST", "dbc-0123abcd-4567.cloud.databricks.com")
    assert settings.current_env() == "dev"


def test_the_workspace_files_stay_out_of_git_and_dev_keeps_the_existing_app_name():
    assert "*.local.yml" in (ROOT / ".gitignore").read_text().split()
    bundle = yaml.safe_load((ROOT / "databricks.yml").read_text(encoding="utf-8"))
    assert bundle["targets"]["dev"]["variables"]["app_name"] == "lakeboard-dev"
    assert "'lakeboard-dev'" in yaml.safe_load((ROOT / ".github/workflows/deploy.yml").read_text())["jobs"]["deploy"]["env"]["APP_NAME"]
