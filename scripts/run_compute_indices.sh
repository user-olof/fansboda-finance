#!/usr/bin/env bash
# One-off index initialization on the production VM: run compute_indices.py as
# the fansboda user for each country set, in order (default: us swe uk).
# Stops at the first country that fails.
#
# Usage (on the VM, as a sudo-capable user):
#   ./scripts/run_compute_indices.sh            # us, swe, uk
#   ./scripts/run_compute_indices.sh uk         # selected countries only
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/fansboda-finance}"
APP_USER="${APP_USER:-fansboda}"
if [[ $# -eq 0 ]]; then
  set -- us swe uk
fi
COUNTRIES=("$@")

for country in "${COUNTRIES[@]}"; do
  case "$country" in
    us|swe|uk) ;;
    *)
      echo "Unknown country: $country (expected us, swe, or uk)" >&2
      exit 1
      ;;
  esac
done

for country in "${COUNTRIES[@]}"; do
  echo "=== compute_indices.py --country $country ==="
  sudo -u "$APP_USER" bash -c '
    set -euo pipefail
    cd "$1"
    set -a; . ./.env; set +a
    PIPENV_VENV_IN_PROJECT=1 pipenv run python compute_indices.py --country "$2"
  ' _ "$APP_DIR" "$country"
done

echo "Done: ${COUNTRIES[*]}"
