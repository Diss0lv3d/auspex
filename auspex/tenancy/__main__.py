"""The tenancy CLI (S30 call 1): the only way to create organizations and
workspaces. Run inside the app container:

    docker compose exec app python -m auspex.tenancy list

Every act is audited with the CLI as its actor. Output never prints an email.
"""

import argparse
import asyncio
import sys

from auspex.config import get_settings
from auspex.db import create_pool
from auspex.tenancy import admin
from auspex.tenancy.region import GLOBAL, REGIONS


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m auspex.tenancy")
    sub = parser.add_subparsers(dest="command", required=True)
    regions = sorted(REGIONS)

    org = sub.add_parser("create-org", help="a direct or provider organization")
    org.add_argument("--kind", choices=["direct", "provider"], required=True)
    org.add_argument("--name", required=True)
    org.add_argument("--workspace", required=True)
    org.add_argument("--admin", required=True, help="the first admin's email")
    org.add_argument("--region", choices=regions, default=GLOBAL)

    client = sub.add_parser("create-client", help="a client under a provider")
    client.add_argument("--provider", required=True)
    client.add_argument("--name", required=True)
    client.add_argument("--workspace", required=True)
    client.add_argument("--region", choices=regions, default=GLOBAL)
    client.add_argument("--admin", default=None)
    client.add_argument("--restricted", action="store_true")

    restricted = sub.add_parser("set-restricted", help="restrict a client, or lift it")
    restricted.add_argument("--client", required=True)
    restricted.add_argument("state", choices=["on", "off"])

    member = sub.add_parser("set-member", help="add a member, or change role and grant")
    member.add_argument("--workspace", required=True)
    member.add_argument("--email", required=True)
    member.add_argument("--role", choices=["admin", "analyst", "viewer"], required=True)
    member.add_argument("--provider-wide", action="store_true")

    remove = sub.add_parser("remove-member")
    remove.add_argument("--workspace", required=True)
    remove.add_argument("--email", required=True)

    sub.add_parser("list", help="organizations, workspaces, regions, member counts")
    return parser


async def _run(args: argparse.Namespace) -> str:
    pool = await create_pool(get_settings().database_url, retries=3, delay=1.0)
    try:
        if args.command == "create-org":
            await admin.create_org(pool, kind=args.kind, name=args.name,
                                   workspace=args.workspace, admin_email=args.admin,
                                   region=args.region)
            return (f"created {args.kind} organization {args.name!r}"
                    f" with workspace {args.workspace!r} ({args.region})")
        if args.command == "create-client":
            await admin.create_client(pool, provider=args.provider, name=args.name,
                                      workspace=args.workspace, region=args.region,
                                      admin_email=args.admin, restricted=args.restricted)
            return (f"created client {args.name!r} of {args.provider!r}"
                    f" with workspace {args.workspace!r} ({args.region})")
        if args.command == "set-restricted":
            await admin.set_restricted(pool, client=args.client, restricted=args.state == "on")
            return f"{args.client!r} restricted: {args.state}"
        if args.command == "set-member":
            await admin.set_member(pool, workspace=args.workspace, email=args.email,
                                   role=args.role, provider_wide=args.provider_wide)
            return f"membership in {args.workspace!r} set: {args.role}"
        if args.command == "remove-member":
            await admin.remove_member_by_email(pool, workspace=args.workspace, email=args.email)
            return f"membership in {args.workspace!r} removed"
        lines = []
        for row in await admin.overview(pool):
            parent = f" of {row['parent']}" if row["parent"] else ""
            flag = " restricted" if row["restricted"] else ""
            where = (f"  {row['workspace']} ({row['region']}, {row['members']} members)"
                     if row["workspace"] else "  (no workspace)")
            lines.append(f"{row['kind']}{flag} {row['org']}{parent}:{where}")
        return "\n".join(lines) or "no organizations"
    finally:
        await pool.close()


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        print(asyncio.run(_run(args)))
    except admin.TenancyError as err:
        print(f"refused: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
