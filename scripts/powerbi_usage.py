"""Who views which Power BI report: pulls "ViewReport" events from the Power BI admin activity log.

Used to plan the migration (which reports matter, who to tell). Power BI keeps this log for about 28 days,
so run it regularly and keep the output if you want a longer history.

    python scripts/powerbi_usage.py --days 28                    # every report
    python scripts/powerbi_usage.py --days 28 --report "Sales Overview" --report "Finance"

Sign-in (read-only admin API, https://learn.microsoft.com/rest/api/power-bi/admin/get-activity-events):
  * default: the current Azure CLI login (`az login`). Works for a Fabric administrator, or for a service principal
    signed in with `az login --service-principal`.
  * --sp: the service principal in AZURE_TENANT_ID / AZURE_CLIENT_ID / AZURE_CLIENT_SECRET (for example your deployment principal).
    A Fabric admin must allow it under Tenant settings > Admin API settings > "Service principals can access
    read-only admin APIs", and the principal must not have any admin-consent Power BI API permissions.

Writes three CSV files to --out (default: usage/, which git ignores because it holds people's email addresses):
  views.csv          one row per report view
  report_users.csv   report x user: views, days used, last viewed    <- the comms list
  reports.csv        report: users, views, last viewed               <- what to migrate first, what to retire
"""
import argparse
import csv
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

API = "https://api.powerbi.com/v1.0/myorg/admin/activityevents"
RESOURCE = "https://analysis.windows.net/powerbi/api"


def token(use_sp: bool) -> str:
    if use_sp:
        body = urllib.parse.urlencode({
            "grant_type": "client_credentials", "client_id": os.environ["AZURE_CLIENT_ID"],
            "client_secret": os.environ["AZURE_CLIENT_SECRET"], "scope": RESOURCE + "/.default",
        }).encode()
        url = f"https://login.microsoftonline.com/{os.environ['AZURE_TENANT_ID']}/oauth2/v2.0/token"
        with urllib.request.urlopen(urllib.request.Request(url, data=body)) as r:
            return json.load(r)["access_token"]
    az = shutil.which("az") or shutil.which("az.cmd")
    if not az:
        raise SystemExit("Azure CLI not found. Install it and run `az login`, or use --sp.")
    out = subprocess.run([az, "account", "get-access-token", "--resource", RESOURCE, "--query", "accessToken", "-o", "tsv"],
                         capture_output=True, text=True)
    if out.returncode:
        raise SystemExit("Could not get a Power BI token from the Azure CLI. Run `az login` first.\n" + out.stderr.strip()[-400:])
    return out.stdout.strip()


def day_events(tok: str, day: dt.date):
    start, end = f"'{day}T00:00:00'", f"'{day}T23:59:59'"
    url = f"{API}?startDateTime={start}&endDateTime={end}&$filter=" + urllib.parse.quote("Activity eq 'ViewReport'")
    while url:
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {tok}"})
        try:
            with urllib.request.urlopen(req) as r:
                page = json.load(r)
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:300]
            if e.code == 400:  # the day is older than the log goes back
                raise LookupError(detail) from e
            hint = " This login is not allowed to read the admin activity log (see the sign-in notes at the top of this script)." if e.code in (401, 403) else ""
            raise SystemExit(f"Power BI returned {e.code} for {day}.{hint}\n{detail}") from e
        yield from page.get("activityEventEntities", [])
        url = None if page.get("lastResultSet") else page.get("continuationUri")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=28, help="how many days back, up to about 28")
    ap.add_argument("--report", action="append", default=[], help="only this report name (repeatable)")
    ap.add_argument("--out", default="usage")
    ap.add_argument("--sp", action="store_true", help="sign in as the service principal in AZURE_* variables")
    a = ap.parse_args()
    tok = token(a.sp)
    wanted = {r.lower() for r in a.report}
    today = dt.datetime.now(dt.timezone.utc).date()
    views = []
    for n in range(a.days, -1, -1):
        day = today - dt.timedelta(days=n)
        count = 0
        try:
            for e in day_events(tok, day):
                name = e.get("ReportName") or ""
                if wanted and name.lower() not in wanted:
                    continue
                count += 1
                views.append({
                    "time_utc": e.get("CreationTime", ""), "user": (e.get("UserId") or "").lower(), "report": name,
                    "report_id": e.get("ReportId", ""), "workspace": e.get("WorkSpaceName", ""), "app": e.get("AppName", ""),
                    "how": e.get("ConsumptionMethod", ""), "dataset": e.get("DatasetName", ""),
                })
        except LookupError:
            print(f"{day}: skipped, Power BI no longer keeps this day", file=sys.stderr)
            continue
        print(f"{day}: {count} views", file=sys.stderr)

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    def write(name: str, rows: list[dict]) -> None:
        with open(out / name, "w", newline="", encoding="utf-8-sig") as f:
            if rows:
                w = csv.DictWriter(f, fieldnames=list(rows[0]))
                w.writeheader()
                w.writerows(rows)

    write("views.csv", views)
    pair = defaultdict(lambda: {"views": 0, "days": set(), "last": ""})
    for v in views:
        p = pair[(v["workspace"], v["report"], v["user"])]
        p["views"] += 1
        p["days"].add(v["time_utc"][:10])
        p["last"] = max(p["last"], v["time_utc"][:10])
    report_users = [{"workspace": k[0], "report": k[1], "user": k[2], "views": p["views"], "days_used": len(p["days"]), "last_viewed": p["last"]}
                    for k, p in sorted(pair.items(), key=lambda kv: (kv[0][0], kv[0][1], -kv[1]["views"]))]
    write("report_users.csv", report_users)
    rep = defaultdict(lambda: {"users": set(), "views": 0, "last": ""})
    for r in report_users:
        x = rep[(r["workspace"], r["report"])]
        x["users"].add(r["user"])
        x["views"] += r["views"]
        x["last"] = max(x["last"], r["last_viewed"])
    reports = [{"workspace": k[0], "report": k[1], "users": len(x["users"]), "views": x["views"], "last_viewed": x["last"]}
               for k, x in sorted(rep.items(), key=lambda kv: -kv[1]["views"])]
    write("reports.csv", reports)
    print(f"{len(views)} views, {len(reports)} reports, {len({v['user'] for v in views})} people -> {out.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
