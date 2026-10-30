"""The connector CLI (S32, spec decision 3): the only way a first-party package is
registered. Run inside the app container:

    docker compose exec app python -m auspex.connectors register --first-party <zip>

It writes into the reserved `__deployment__` workspace (D-035, D-068), creating it with
the scorecard's own upsert if missing; every workspace then lists the package. A
workspace's admin registers its own packages over the API (Task 11), never here.
"""

import argparse
import asyncio
import sys
from pathlib import Path

from auspex_sdk.package import MAX_PACKAGE_BYTES

from auspex.config import get_settings
from auspex.connectors.catalogue import RegistrationRefused, register
from auspex.db import create_pool
from auspex.llm.scorecard import ensure_deployment_workspace


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m auspex.connectors")
    sub = parser.add_subparsers(dest="command", required=True)
    reg = sub.add_parser("register", help="register a first-party connector package")
    # Required, and spelled out: the act is first-party registration, and the flag
    # says so at the prompt where it is typed.
    reg.add_argument("--first-party", action="store_true", required=True)
    reg.add_argument("zip", type=Path, help="a package built by `auspex-sdk build`")
    return parser


async def run(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        # Sized from the file system first: a wrong path to a huge file is never read.
        if args.zip.stat().st_size > MAX_PACKAGE_BYTES:
            print(f"refused: {args.zip} is over the {MAX_PACKAGE_BYTES} byte package limit",
                  file=sys.stderr)
            return 1
        data = args.zip.read_bytes()
    except OSError as err:
        print(f"refused: cannot read {args.zip}: {err.strerror}", file=sys.stderr)
        return 1
    pool = await create_pool(get_settings().database_url, retries=3, delay=1.0)
    try:
        entry = await register(
            pool,
            workspace_id=await ensure_deployment_workspace(pool),
            data=data,
            registered_by=None,
            offered_to_clients=False,
            first_party=True,
        )
    except RegistrationRefused as err:
        print(f"refused: {err.reason}", file=sys.stderr)
        return 1
    finally:
        await pool.close()
    print(f"registered first-party {entry.connector_id} {entry.version} ({entry.content_hash})")
    return 0


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(run(argv))


if __name__ == "__main__":
    sys.exit(main())
