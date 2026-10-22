"""The `auspex-sdk` command line (S32). `build` now; Task 6 adds `run`."""

import argparse
import sys
from pathlib import Path

from auspex_sdk.build import BuildError, build
from auspex_sdk.manifest import ManifestError
from auspex_sdk.package import PackageError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="auspex-sdk", description="Auspex connector SDK")
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build", help="build a connector's manifest.json and package zip")
    b.add_argument("source_dir", type=Path)
    args = parser.parse_args(argv)
    try:
        path, digest = build(args.source_dir)
    except (ManifestError, PackageError, BuildError) as e:
        print(f"auspex-sdk: {' '.join(str(e).split())}", file=sys.stderr)
        return 1
    print(digest)
    print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
