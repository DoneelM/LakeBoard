"""Scaffolds src/dashboards/<slug>/ with a manifest, an example dataset and a starter page.

    python scripts/new_dashboard.py my-dashboard "My dashboard" --owner Finance --section Finance
"""
import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "src" / "dashboards"

MANIFEST = """title: {title}
description: TODO one sentence on the question this dashboard answers.
owner: {owner}
section: {section}
groups: []          # workspace groups allowed to open it ([] = everyone with access to the portal)
order: 100
environments: [dev, test]   # remove this line when it is ready for prod
datasets:
  example:
    title: Example dataset
    description: TODO what it reads.
    sql: sql/example.sql
    cache_ttl: 1h
"""
SQL = """-- TODO: one SELECT/WITH statement. Write tables as catalog.schema.table, using the prod catalog name
-- (an allowed catalog in src/environments.yml). Use :name parameters and declare them under params in dashboard.yml.
-- This example reads the built-in samples catalog.
SELECT date_format(o_orderdate, 'yyyy-MM') AS month, round(sum(o_totalprice), 0) AS revenue
FROM samples.tpch.orders
WHERE o_orderdate >= DATE'1997-01-01'
GROUP BY 1
ORDER BY 1
"""
PAGE = """<div class="kit-page">
  <h1>{title}</h1>
  <p class="kit-sub">TODO one line on what this shows.</p>
  <div id="ex-tiles"></div>
  <div class="kit-grid" style="margin-top:12px">
    <div class="kit-card"><h2>Revenue by month</h2><div id="ex-chart"></div></div>
    <div class="kit-card"><h2>Detail</h2><div id="ex-table"></div></div>
  </div>
</div>
<script>
// Building blocks are documented in docs/AUTHORING.md.
dash.onData(() => {{
  const d = dash.data('example');
  if (!kit.ready('#ex-chart', d)) return;
  const total = d.data.reduce((sum, r) => sum + (kit.num(r.revenue) || 0), 0);
  kit.tiles('#ex-tiles', [{{ label: 'Revenue', value: kit.fmt.money(total) }}, {{ label: 'Months', value: kit.fmt.num(d.data.length) }}]);
  kit.line('#ex-chart', {{ rows: d.data, x: 'month', series: [{{ key: 'revenue', label: 'Revenue' }}] }});
  kit.table('#ex-table', {{ rows: d.data, csv: 'revenue-by-month', columns: [
    {{ key: 'month', label: 'Month', fmt: kit.fmt.month }},
    {{ key: 'revenue', label: 'Revenue', align: 'right', fmt: kit.fmt.money }},
  ] }});
}});
</script>
"""
README = """# {title}

Replaces: TODO (Power BI report and workspace), or "new".

| Power BI page | Here |
|---|---|
| TODO | TODO |

Reconciliation (period, filters, Power BI value, dashboard value): TODO
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slug")
    ap.add_argument("title")
    ap.add_argument("--owner", default="")
    ap.add_argument("--section", default="Other", help="left navigation heading (see src/environments.yml)")
    a = ap.parse_args()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", a.slug):
        raise SystemExit("slug: lowercase letters, digits and hyphens")
    d = ROOT / a.slug
    if d.exists():
        raise SystemExit(f"{d} already exists")
    (d / "sql").mkdir(parents=True)
    (d / "dashboard.yml").write_text(MANIFEST.format(title=a.title, owner=a.owner, section=a.section), encoding="utf-8")
    (d / "sql" / "example.sql").write_text(SQL, encoding="utf-8")
    (d / "index.html").write_text(PAGE.format(title=a.title), encoding="utf-8")
    (d / "README.md").write_text(README.format(title=a.title), encoding="utf-8")
    print(f"created {d}")


if __name__ == "__main__":
    main()
