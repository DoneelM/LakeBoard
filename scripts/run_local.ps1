# Runs the portal on http://localhost:8000 using your Databricks CLI profile in place of the forwarded user token.
#   ./scripts/run_local.ps1 -Profile <cli-profile> -Warehouse <warehouse-id> [-Env prod]
# -Profile is a profile in ~/.databrickscfg (`databricks auth login` creates one). -Warehouse is a SQL warehouse id
# (SQL Warehouses > your warehouse > Connection details). -Env picks which catalogs the SQL reads (src/environments.yml).
param(
  [Parameter(Mandatory = $true)][string]$Profile,
  [Parameter(Mandatory = $true)][string]$Warehouse,
  [string]$Env = "prod"
)
$env:PORTAL_LOCAL_PROFILE = $Profile
$env:DATABRICKS_WAREHOUSE_ID = $Warehouse
$env:PORTAL_ENV = $Env
$env:PORTAL_WARM = "0"   # don't pre-load shared datasets from a laptop
Push-Location (Join-Path $PSScriptRoot "..\src")
try { python -m uvicorn app:app --host 127.0.0.1 --port 8000 --reload }
finally { Pop-Location }
