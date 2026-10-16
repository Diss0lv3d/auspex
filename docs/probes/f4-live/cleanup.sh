#!/usr/bin/env bash
# F4 live check: delete exactly what seed.sh made (and the chats its people
# made, by cascade), then prove nothing is left.
set -euo pipefail
cd "$(dirname "$0")/../../.."
IDS="SELECT id FROM organizations WHERE name LIKE 'f4-live-%' OR name LIKE '%onerror=alert(1)%'"
q() { docker compose exec -T postgres psql -U auspex -d auspex -v ON_ERROR_STOP=1 -c "$1"; }
q "BEGIN;
 DELETE FROM workspaces WHERE org_id IN ($IDS);
 DELETE FROM users WHERE home_org_id IN ($IDS) OR email LIKE '%@f4-live.auspex.dev';
 DELETE FROM organizations WHERE id IN ($IDS) AND kind = 'client';
 DELETE FROM organizations WHERE id IN ($IDS);
 COMMIT;"
q "SELECT count(*) AS users_left FROM users WHERE email LIKE '%@f4-live.auspex.dev'
   UNION ALL SELECT count(*) FROM organizations WHERE name LIKE 'f4-live-%' OR name LIKE '%onerror=alert(1)%'"
