#!/usr/bin/env bash
# Runs the portal on http://localhost:8000 using your Databricks CLI profile in place of the forwarded user token.
#   ./scripts/run_local.sh <cli-profile> <warehouse-id> [env]
# <cli-profile> is a profile in ~/.databrickscfg (`databricks auth login` creates one). <warehouse-id> is a SQL
# warehouse id (SQL Warehouses > your warehouse > Connection details). [env] picks which catalogs the SQL reads
# (src/environments.yml); default prod.
set -euo pipefail
if [ $# -lt 2 ]; then
  echo "usage: $0 <cli-profile> <warehouse-id> [dev|test|prod]" >&2
  exit 2
fi
export PORTAL_LOCAL_PROFILE="$1"
export DATABRICKS_WAREHOUSE_ID="$2"
export PORTAL_ENV="${3:-prod}"
export PORTAL_WARM=0   # don't pre-load shared datasets from a laptop
cd "$(dirname "$0")/../src"
exec python -m uvicorn app:app --host 127.0.0.1 --port 8000 --reload
