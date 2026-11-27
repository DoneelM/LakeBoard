"""Browser smoke test of the local app with stubbed data.

Run: pip install playwright && python -m playwright install chromium && python -m pytest e2e -q
"""
import re
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

import pytest

pytest.importorskip("playwright.sync_api")

ROOT = Path(__file__).resolve().parent.parent
# Stub rows for City Trips, shaped like its SQL results (every value a string, as the API sends them).
_DAYS = [f"2016-01-{d:02d}" for d in range(1, 32)] + [f"2016-02-{d:02d}" for d in range(1, 30)]
_AREAS = ["Manhattan", "Brooklyn", "Queens", "LaGuardia"]
FIXTURES = {
    "daily": (
        ["day", "trips", "fares", "miles", "minutes"],
        [[d, str(n), str(n * 12), str(n * 3), str(n * 14)]
         for i, d in enumerate(_DAYS) for n in [80 if d == "2016-01-23" else 330 + (i * 7) % 90]],
    ),
    "hourly": (
        ["hour_start", "trips"],
        [[f"{d} {h:02d}:00", str(3 if d == "2016-01-23" else 2 + (h * 5 + i) % 25)] for i, d in enumerate(_DAYS) for h in range(24)
         if not (d == "2016-01-23" and h >= 9)],   # a storm: a few early trips, then none
    ),
    "pace": (
        ["hour", "part", "trips", "miles", "hours"],
        [[str(h), part, str(200 + h * 10), str(500 + h * 20), str(30 + h * 4)] for part in ("weekday", "weekend") for h in range(24)],
    ),
    "hours": (
        ["weekday", "hour", "trips"],
        [[str(w), str(h), str(20 + (w * 7 + h * 3) % 200)] for w in range(7) for h in range(24)],
    ),
    "flows": (
        ["from_area", "to_area", "trips", "fares", "miles"],
        [[a, b, str(18000 if a == b == "Manhattan" else 300), str(180000 if a == b == "Manhattan" else 9000), str(30000 if a == b == "Manhattan" else 1500)]
         for a in _AREAS for b in _AREAS],
    ),
    "zips": (
        ["direction", "zip", "trips", "avg_fare"],
        [[d, str(10001 + i), str(1200 - i * 50), "12.50"] for d in ("pickup", "dropoff") for i in range(10)],
    ),
    "bands": (
        ["band_order", "band", "trips", "p10", "p25", "median", "p75", "p90"],
        [[str(i + 1), b, str(5000 - i * 900), str(4 + i * 6), str(5 + i * 7), str(6 + i * 8), str(8 + i * 9), str(10 + i * 10)]
         for i, b in enumerate(["Under 1 mi", "1–2 mi", "2–5 mi", "5–10 mi", "10 mi or more"])],
    ),
}


def _payload(dataset):
    columns, rows = FIXTURES[dataset]
    return {"columns": columns, "rows": rows, "fetched_at": 1.7e9, "expires_at": 1.7e9 + 86400,
            "cached": True, "cache": "shared", "data_through": None, "cut": False}


@pytest.fixture(scope="module")
def base_url():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    proc = subprocess.Popen([sys.executable, "e2e/stub_server.py", str(port)], cwd=ROOT,
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    url = f"http://127.0.0.1:{port}"
    try:
        deadline = time.time() + 30
        while True:
            try:
                if urllib.request.urlopen(url + "/healthz", timeout=1).status == 200:
                    break
            except OSError:
                pass
            if proc.poll() is not None or time.time() > deadline:
                proc.terminate()
                pytest.fail("stub server did not start: " + proc.communicate()[1])
            time.sleep(0.2)
        yield url
    finally:
        proc.terminate()
        proc.communicate()


def test_portal_and_dashboard_load(base_url):
    from playwright.sync_api import sync_playwright

    errors, hosts = [], set()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.on("console", lambda m: m.type == "error" and errors.append(m.text))
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("request", lambda r: hosts.add(urlparse(r.url).netloc))
        page.route("**/api/d/*/sources", lambda r: r.fulfill(json={"datasets": {}}))
        page.route("**/api/d/*/data/*", lambda r: r.fulfill(json=_payload(r.request.url.split("?")[0].rsplit("/", 1)[1])))

        page.goto(base_url + "/")
        assert "Dashboards" in page.title()
        assert page.locator(".pc-card").count() >= 1

        page.goto(base_url + "/d/city-trips", wait_until="networkidle")
        assert "City Trips" in page.title()
        assert page.get_by_text(re.compile(r"fell \d+% below a normal Saturday")).first.is_visible()  # the headline, worked out from the data
        assert page.locator("#ct-tiles .kit-tile").count() == 5
        assert page.locator("#ct-trend svg .kit-mark").count() >= 1                      # the storm is marked on the chart
        assert page.locator("#ct-flow svg path.ct-rib").count() >= 1
        assert page.locator("#dash-root svg").count() >= 6
        browser.close()

    assert not errors, errors
    assert hosts == {base_url.removeprefix("http://")}, hosts
