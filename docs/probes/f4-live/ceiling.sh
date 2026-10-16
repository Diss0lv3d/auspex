#!/usr/bin/env bash
# F4 live walk: put `default`'s inference counter at the ceiling for one
# refused turn (no engine call), then put it back exactly (B2's trick,
# docs/probes/b2-b008/probe_live_ceiling.py). State: the window and the old
# value, saved by `set` and consumed by `restore`.
set -euo pipefail
cd "$(dirname "$0")/../../.."
STATE="${STATE:-/tmp/f4-ceiling.state}"
q() { docker compose exec -T postgres psql -U auspex -d auspex -At -v ON_ERROR_STOP=1 -c "$1"; }
WS=$(q "SELECT id FROM workspaces WHERE name = 'default'")
case "$1" in
  set)
    WIN=$(q "SELECT date_trunc('hour', now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'")
    OLD=$(q "SELECT used FROM usage_counters WHERE workspace_id = '$WS' AND meter = 'inference_calls' AND window_start = '$WIN'")
    printf '%s\n%s\n' "$WIN" "$OLD" > "$STATE"
    q "INSERT INTO usage_counters (workspace_id, meter, window_start, used) VALUES ('$WS', 'inference_calls', '$WIN', 1000000)
       ON CONFLICT (workspace_id, meter, window_start) DO UPDATE SET used = 1000000" >/dev/null
    echo "window $WIN: used ${OLD:-<none>} -> 1000000" ;;
  restore)
    WIN=$(sed -n 1p "$STATE"); OLD=$(sed -n 2p "$STATE")
    if [ -z "$OLD" ]; then
      q "DELETE FROM usage_counters WHERE workspace_id = '$WS' AND meter = 'inference_calls' AND window_start = '$WIN'" >/dev/null
    else
      q "UPDATE usage_counters SET used = $OLD WHERE workspace_id = '$WS' AND meter = 'inference_calls' AND window_start = '$WIN'" >/dev/null
    fi
    echo "window $WIN restored to: $(q "SELECT coalesce(used::text, '<none>') FROM usage_counters WHERE workspace_id = '$WS' AND meter = 'inference_calls' AND window_start = '$WIN'")${OLD:+ (was $OLD)}"
    rm -f "$STATE" ;;
esac
