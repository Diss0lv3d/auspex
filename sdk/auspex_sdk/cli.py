"""The `auspex-sdk` command line (S32): `build` a package, `run` one command on a fixture."""

import argparse
import json
import sys
from pathlib import Path

from auspex_sdk.build import BuildError, build
from auspex_sdk.harness import HarnessError, run_command
from auspex_sdk.http import HostNotDeclared
from auspex_sdk.manifest import ManifestError
from auspex_sdk.package import PackageError
from auspex_sdk.results import ResultError
from auspex_sdk.runtime import ConfigError


def _json_file(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise HarnessError(f"{path}: cannot be read as JSON: {e}") from e
    if not isinstance(data, dict):
        raise HarnessError(f"{path}: expected a JSON object")
    return data


def _run(args: argparse.Namespace) -> int:
    result = run_command(
        args.source_dir,
        args.command,
        config=_json_file(args.config),
        secrets=_json_file(args.secrets) if args.secrets else {},
        fixture=args.fixture,
        arguments=_json_file(args.arguments) if args.arguments else None,
    )
    print(json.dumps(result, sort_keys=True, indent=2, ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="auspex-sdk", description="Auspex connector SDK")
    sub = parser.add_subparsers(dest="subcommand", required=True)
    b = sub.add_parser("build", help="build a connector's manifest.json and package zip")
    b.add_argument("source_dir", type=Path)
    r = sub.add_parser("run", help="run one command against recorded HTTP exchanges")
    r.add_argument("source_dir", type=Path)
    r.add_argument("command", help="test, fetch, or <action>.<dry_run|execute|undo|observe>")
    r.add_argument("--config", type=Path, required=True, help="JSON file: the config values")
    r.add_argument("--secrets", type=Path, help="JSON file: secret field name -> value")
    r.add_argument("--fixture", type=Path, required=True, help="JSON file: recorded exchanges")
    r.add_argument("--arguments", type=Path, help="JSON file: action params, or cursor/limit")
    args = parser.parse_args(argv)
    try:
        if args.subcommand == "run":
            return _run(args)
        path, digest = build(args.source_dir)
    except (
        ManifestError,
        PackageError,
        BuildError,
        HarnessError,
        ResultError,
        HostNotDeclared,
        ConfigError,
    ) as e:
        print(f"auspex-sdk: {' '.join(str(e).split())}", file=sys.stderr)
        return 1
    print(digest)
    print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
