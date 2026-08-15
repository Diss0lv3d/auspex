"""Demo helper — file one real proposal and print its id.

`propose` is a code seam (`settlement.action_proposer`), not an HTTP route: the
agent loop calls it when a model asks for an action, and S18 deliberately did
not expose "create a proposal" to the network. So the demo files one the way
the platform really does, then drives approve/undo over the real HTTP surface.

Prints two lines to stdout for the shell to read:
    PROPOSAL <uuid>
    OBSERVABLE <obs_id>
Everything else goes to stderr so the demo can narrate without polluting them.

Run in-container (`docker compose exec -T app python /srv/auspex/scripts/...`)
so it exercises the installed distribution, or from the host with .venv.
"""

import asyncio
import json
import os
import sys

import asyncpg

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from auspex.actions.builtin import build_builtin_actions  # noqa: E402
from auspex.actions.settlement import action_proposer  # noqa: E402

DSN = os.environ.get("DATABASE_URL", "postgresql://auspex:auspex@localhost:55432/auspex")
OBS_ID = "demo-obs-1"
OBS_VALUE = "mail.paypa1.com"


def note(msg: str) -> None:
    print(msg, file=sys.stderr)


async def main() -> None:
    pool = await asyncpg.create_pool(DSN, min_size=1, max_size=2)
    try:
        # The demo user's workspace — every dev-login lands in `default`.
        ws = await pool.fetchval("SELECT id FROM workspaces WHERE name = 'default'")
        if ws is None:
            note("no `default` workspace — run a dev-login first")
            sys.exit(1)

        # A lookalike domain to annotate. Idempotent so the demo can be re-run:
        # the table's uniqueness is (workspace_id, type, value) — obs_id is an
        # indexed handle, not a key — so conflict on that and take back whatever
        # obs_id the row already carries rather than assuming ours won.
        obs_id = await pool.fetchval(
            """
            INSERT INTO observables (workspace_id, obs_id, type, value)
            VALUES ($1::uuid, $2, 'domain', $3)
            ON CONFLICT (workspace_id, type, value)
                DO UPDATE SET last_seen = now()
            RETURNING obs_id
            """,
            ws,
            OBS_ID,
            OBS_VALUE,
        )

        spec = build_builtin_actions(pool)[0]
        propose = action_proposer(pool)

        row = await propose(
            spec=spec,
            arguments={"observable_id": obs_id, "note": "Confirmed phishing infrastructure."},
            workspace_id=ws,
        )

        card = row["card"] if isinstance(row["card"], dict) else json.loads(row["card"])
        note("")
        note(f"  DRY RUN : {card['summary']}")
        note(f"  RISK    : {card['risk']}   reversible: {card['reversible']}")
        note(f"  SYSTEMS : {json.dumps(card['systems'])}")
        note(f"  FPRINT  : {row['spec_fingerprint'][:16]}…")
        note(f"  STATUS  : {row['status']}")
        note("")
        note("  The summary is the ACTION's sentence about the real target — the")
        note("  domain was resolved from the workspace and the note measured.")
        note("  The dry run wrote nothing.")

        print(f"PROPOSAL {row['id']}")
        print(f"OBSERVABLE {obs_id}")
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
