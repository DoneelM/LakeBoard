"""Shared test helpers: small dashboards written to a temporary folder, so tests never depend on the real ones."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def write_dashboard(root: Path, slug: str, manifest: str, sql: dict[str, str], page: str = "") -> Path:
    """src/dashboards/<slug>/ in miniature: dashboard.yml, sql/<name>.sql and index.html. Returns the folder."""
    d = root / slug
    (d / "sql").mkdir(parents=True)
    (d / "dashboard.yml").write_text(manifest, encoding="utf-8")
    for name, text in sql.items():
        (d / "sql" / f"{name}.sql").write_text(text, encoding="utf-8")
    if page is not None:
        (d / "index.html").write_text(page or "".join(f"<script>dash.data('{k}')</script>" for k in sql), encoding="utf-8")
    return d


@pytest.fixture()
def make_dashboard(tmp_path):
    """make_dashboard(slug, manifest, {name: sql}, page='') -> folder, under this test's tmp_path."""
    return lambda slug, manifest, sql, page="": write_dashboard(tmp_path, slug, manifest, sql, page)
