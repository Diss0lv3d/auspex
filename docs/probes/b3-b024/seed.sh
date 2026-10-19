#!/usr/bin/env bash
# B3 / B-024 live check: an MSSP with three clients, and a provider-wide
# analyst who can enter all four workspaces, so one arrow step on the switcher
# can be seen passing through a client. Synthetic addresses only; cleanup.sh
# deletes all of it.
set -euo pipefail
cd "$(dirname "$0")/../../.."
D=b3-live.auspex.dev
t() { docker compose exec -T app python -m auspex.tenancy "$@"; }
t create-org --kind provider --name b3-live-mssp --workspace b3-live-mssp --admin "p-admin@$D"
for c in alpha bravo charlie; do
  t create-client --provider b3-live-mssp --name "b3-live-$c" --workspace "b3-live-$c"
done
t set-member --workspace b3-live-mssp --email "m-wide@$D" --role analyst --provider-wide
t list | grep -E "b3-live" || true
