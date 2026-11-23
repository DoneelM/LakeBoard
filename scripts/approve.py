"""Records a data-team review of a dashboard's page code and shared SQL (decision 0018).

    python scripts/approve.py <slug>            # prints the digests for src/reviewed_pages.yml and src/shared_cache.yml
    python scripts/approve.py <slug> --write    # writes them into those files, replacing the slug's old entries

Run it only after reading the page (index.html and any assets/) and, for every `cache: shared` dataset, the SQL:
a shared result is served to every viewer, so it must not depend on who runs it (no row filters, column masks or
current_user()). The digests make any later edit fail the checks until someone reviews it again.
"""
import argparse
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from portal.registry import DASHBOARDS_DIR, REVIEWED_PAGES, SHARED_APPROVALS, digest, load_assets  # noqa: E402

HEADERS = {
    REVIEWED_PAGES: "# Reviewed dashboard page code: SHA-256 of index.html (and of each assets/ file of an artifact page) as\n"
                    "# UTF-8 text with LF line endings. Review the page before changing a digest. See decision 0018.\n",
    SHARED_APPROVALS: "# Reviewed SQL for cache: shared datasets: SHA-256 of the SQL file as UTF-8 text with LF line endings.\n"
                      "# One result is served to every viewer, so check for row filters, masks and current_user() first.\n",
}


def entries(slug: str) -> dict[Path, dict[str, str]]:
    folder = DASHBOARDS_DIR / slug
    manifest = yaml.safe_load((folder / "dashboard.yml").read_text(encoding="utf-8")) or {}
    pages = {slug: digest(folder / "index.html")}
    assets, _ = load_assets(folder, manifest.get("page") == "artifact")
    pages.update({f"{slug}/assets/{name}": digest(path) for name, path in assets.items()})
    shared = {f"{slug}/{ds_id}": digest(folder / spec["sql"])
              for ds_id, spec in (manifest.get("datasets") or {}).items()
              if spec.get("cache") == "shared" and spec.get("auth", "user") == "user" and not spec.get("todo")}
    return {REVIEWED_PAGES: pages, SHARED_APPROVALS: shared}


def write(path: Path, slug: str, new: dict[str, str]) -> None:
    old = yaml.safe_load(path.read_text(encoding="utf-8")) if path.is_file() else None
    kept = {k: v for k, v in (old or {}).items() if k != slug and not k.startswith(f"{slug}/")}
    merged = dict(sorted({**kept, **new}.items()))
    body = "".join(f"{k}: {v}\n" for k, v in merged.items())
    path.write_text(HEADERS[path] + body, encoding="utf-8", newline="\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("slug")
    ap.add_argument("--write", action="store_true", help="update the approval files instead of printing")
    args = ap.parse_args()
    if not (DASHBOARDS_DIR / args.slug / "dashboard.yml").is_file():
        print(f"no dashboard at src/dashboards/{args.slug}")
        return 1
    for path, new in entries(args.slug).items():
        if args.write:
            write(path, args.slug, new)
            print(f"updated src/{path.name}: {len(new)} entries for {args.slug}")
        else:
            print(f"# src/{path.name}")
            print("".join(f"{k}: {v}\n" for k, v in new.items()) or "(nothing)\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
