#!/usr/bin/env bash
# F4 live check (Task 11): the cast, built with the tenancy CLI (organizations
# are CLI-only, D-068). Synthetic addresses only; cleanup.sh deletes all of it.
set -euo pipefail
cd "$(dirname "$0")/../../.."
D=f4-live.auspex.dev
HOSTILE='<img src=x onerror=alert(1)> ‮ a very long client name that goes on and on'
t() { docker compose exec -T app python -m auspex.tenancy "$@"; }
t create-org --kind provider --name f4-live-mssp --workspace f4-live-mssp --admin "p-admin@$D"
t create-client --provider f4-live-mssp --name f4-live-bank --workspace f4-live-bank --admin "c-admin@$D"
t create-client --provider f4-live-mssp --name f4-live-telco --workspace f4-live-telco --region ksa
t create-client --provider f4-live-mssp --name "$HOSTILE" --workspace "$HOSTILE"
t set-member --workspace f4-live-mssp --email "m-wide@$D" --role analyst --provider-wide
t set-member --workspace f4-live-bank --email "c-analyst@$D" --role analyst
t set-member --workspace f4-live-bank --email "c-viewer@$D" --role viewer
t list | grep -E "f4-live|onerror" || true
