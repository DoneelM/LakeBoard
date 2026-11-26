#!/usr/bin/env bash
# Deploys the bundle to one target, and updates the app when it already exists (decision 0020).
#   bash scripts/deploy_bundle.sh <target>
#
# Each identity that deploys keeps its own bundle state under its own root_path (databricks.yml). An app created by
# hand, or deployed by a person, is unknown to the CI service principal's state, so a plain `bundle deploy` tries to
# create it and fails with "An app with the same name already exists". For that one failure only, this binds the
# existing app to the bundle (`bundle deployment bind`) and deploys again, so the deploy updates it. Any other
# failure fails as before. Pipelines: .github/workflows/deploy.yml and pipelines/deploy-steps.yml.
set -uo pipefail

target="${1:?usage: bash scripts/deploy_bundle.sh <target>}"
log="$(mktemp)"
trap 'rm -f "$log"' EXIT

databricks bundle deploy -t "$target" 2>&1 | tee "$log"
status=${PIPESTATUS[0]}
if [ "$status" -eq 0 ]; then
  exit 0
fi

# Only the bundle's own app clashing with an existing app of the same name. Anything else is a real failure.
if ! grep -q 'resources\.apps\.portal' "$log" || ! grep -q 'ALREADY_EXISTS' "$log"; then
  exit "$status"
fi

# The name the bundle tried to create (variable app_name for this target), not a name passed in separately.
app="$(databricks bundle validate -t "$target" -o json \
  | python -c "import json,sys; print(json.load(sys.stdin)['resources']['apps']['portal']['name'])")" || {
  echo "Could not read the app name from the bundle for target $target." >&2
  exit 1
}

echo "The app $app already exists but this deployer's bundle state doesn't know it. Binding it to the bundle, then deploying again."
if ! databricks bundle deployment bind portal "$app" -t "$target" --auto-approve; then
  echo "Could not bind the existing app $app to the bundle. The identity running this deploy needs CAN MANAGE on" >&2
  echo "the app (Compute > Apps > $app > Permissions). See docs/OPERATIONS.md, 'First CI deploy to an app that already exists'." >&2
  exit 1
fi
databricks bundle deploy -t "$target"
