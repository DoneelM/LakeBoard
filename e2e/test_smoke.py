"""Browser smoke test of the local app with stubbed data.

Run: pip install playwright && python -m playwright install chromium && python -m pytest e2e -q
"""
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
REGIONS = ["AFRICA", "AMERICA", "ASIA", "EUROPE", "MIDDLE EAST"]
SEGMENTS = ["AUTOMOBILE", "BUILDING", "FURNITURE", "HOUSEHOLD", "MACHINERY"]
FIXTURES = {
    "yearly": (
        ["region", "order_year", "revenue", "orders"],
        [[r, str(1992 + j), str(int(1e9 + i * 1e8 + j * 5e7)), str(10000 + i * 100 + j)]
         for i, r in enumerate(REGIONS) for j in range(6)],
    ),
    "segments": (
        ["region", "segment", "revenue", "orders", "customers"],
        [[r, s, str(int(2e9 + i * 1e8 + j * 1e7)), str(30000 + j), str(5000 + i)]
         for i, r in enumerate(REGIONS) for j, s in enumerate(SEGMENTS)],
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

        page.goto(base_url + "/d/artifact-demo", wait_until="networkidle")
        assert "Artifact Demo" in page.title()
        assert page.get_by_text("Orders by region").first.is_visible()
        assert page.locator("#dash-root svg").count() >= 1
        browser.close()

    assert not errors, errors
    assert hosts == {base_url.removeprefix("http://")}, hosts
