"""Check the active LakeBoard deployment's health and Databricks security scan (read-only)."""
import argparse
from urllib.parse import urlsplit

import requests
from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import DatabricksError

SCAN_PREFIX = "APP_DEPLOYMENT_SCAN_STATUS_"
TRIAGED = {"SCAN_FINDING_STATUS_RESOLVED", "SCAN_FINDING_STATUS_IGNORED"}


def enum_value(value):
    return getattr(value, "value", value) or "UNSPECIFIED"


def assess_scan(status, omitted, findings, tracked_rule=None):
    """Return a review result. A tracked finding counts even if someone triaged it."""
    if tracked_rule and any(f.rule_id == tracked_rule for f in findings):
        return "Tracked rule still appears on this deployment. Review the source and rescan."
    if any(enum_value(f.severity) == "SCAN_FINDING_SEVERITY_ERROR" and enum_value(f.status) not in TRIAGED
           for f in findings):
        return "Open critical findings need review."
    if status not in {"CLEAN", "FINDINGS"} or omitted or (status == "FINDINGS" and not findings):
        return "Scan coverage could not be verified. Review the Security tab before treating this deployment as cleared."
    return None


def review_health(workspace, url, expected_env):
    origin = urlsplit(url or "")
    # Use the app URL from the authenticated workspace and never forward its token across redirects.
    if (origin.scheme != "https" or not (origin.hostname or "").endswith(".databricksapps.com")
            or origin.username or origin.password or origin.port not in (None, 443)):
        print("Health check could not verify the Databricks Apps URL.")
        return False
    with requests.Session() as session:
        session.trust_env = False
        response = session.get(f"https://{origin.hostname}/api/health", headers=workspace.config.authenticate(),
                               timeout=20, allow_redirects=False)
    if response.status_code != 200:
        print(f"Portal health: HTTP {response.status_code}. Check app access or runtime logs.")
        return False
    health = response.json()
    print(f"Portal health: {health['env']}, {health['dashboards']} dashboards, "
          f"{len(health['broken'])} broken, {response.elapsed.total_seconds():.2f}s HTTP")
    if health["env"] != expected_env:
        print(f"Expected environment {expected_env}. Check the app's environment configuration.")
    return health["ok"] is True and health["env"] == expected_env and not health["broken"]


def review_security(workspace, app_name, deployment_id, tracked_rule):
    deployment = workspace.apps.get_deployment(app_name, deployment_id)
    status = enum_value(getattr(deployment, "scan_status", None)).removeprefix(SCAN_PREFIX)
    omitted = getattr(deployment, "scan_omitted_findings_count", None) or 0
    print(f"Security scan: {status}")
    list_findings = getattr(workspace.apps, "list_app_deployment_scan_findings", None)
    if list_findings is None:
        print("The local Databricks SDK lacks the scan findings API. Use a current SDK or review Security in the workspace.")
        return False
    findings = list(list_findings(f"apps/{app_name}/deployments/{deployment_id}"))
    print(f"Findings: {len(findings)} listed, {omitted} omitted")
    for finding in findings:
        severity = enum_value(finding.severity).removeprefix("SCAN_FINDING_SEVERITY_")
        triage = enum_value(finding.status).removeprefix("SCAN_FINDING_STATUS_")
        print(f"  {severity} {triage} {finding.rule_id} {finding.file_path}:{finding.line}")
    problem = assess_scan(status, omitted, findings, tracked_rule)
    if problem:
        print(problem)
    elif tracked_rule:
        print(f"Tracked rule absent from the completed scan: {tracked_rule}")
    return problem is None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True, help="Explicit workspace CLI profile")
    parser.add_argument("--app", required=True, help="Databricks app name")
    parser.add_argument("--env", required=True, choices=("dev", "test", "prod"))
    parser.add_argument("--deployment", help="Require this exact active deployment ID")
    parser.add_argument("--tracked-rule", help="Require this scanner rule to be absent, regardless of triage state")
    args = parser.parse_args()
    try:
        workspace = WorkspaceClient(profile=args.profile)
        app = workspace.apps.get(args.app)
        deployment = app.active_deployment
        if not deployment or not deployment.deployment_id:
            print("The app has no active deployment.")
            return 1
        deployment_id = deployment.deployment_id
        runtime = enum_value(getattr(app.app_status, "state", None))
        state = enum_value(getattr(deployment.status, "state", None))
        print(f"{args.app}: {runtime}, active deployment {deployment_id} ({state})")
        if args.deployment and args.deployment != deployment_id:
            print("The expected deployment is not active.")
            return 1
        healthy = False
        if runtime == "RUNNING" and state == "SUCCEEDED":
            try:
                healthy = review_health(workspace, app.url, args.env)
            except (requests.RequestException, ValueError, KeyError, TypeError) as error:
                print(f"Portal health could not be verified ({type(error).__name__}). Check app access and logs.")
        security_ok = review_security(workspace, args.app, deployment_id, args.tracked_rule)
    except (DatabricksError, ValueError) as error:
        print(f"Databricks review could not complete ({type(error).__name__}). Check the chosen profile and app permissions.")
        return 1
    print("Review Insights > System metrics in the workspace for traffic, latency, CPU and memory.")
    return 0 if healthy and security_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
