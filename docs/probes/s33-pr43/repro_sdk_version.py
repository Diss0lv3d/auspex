"""S33 Step 0: PR #43 review finding 10. The same connector source, built by two SDK
versions, should be one package. Builds the reference connector (YAML form) into a
scratch copy twice with `sdk_version()` patched, and compares the content hashes.

    python docs/probes/s33-pr43/repro_sdk_version.py
"""
import shutil
import sys
import tempfile
from pathlib import Path

from auspex_sdk import build as b

SRC = Path(__file__).resolve().parents[3] / "examples/connectors/mock_siem/yaml"
hashes = {}
for version in ("0.1.0", "0.2.0"):
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "c"
        shutil.copytree(SRC, copy, ignore=shutil.ignore_patterns("dist", "__pycache__"))
        b.sdk_version = lambda v=version: v
        _, hashes[version] = b.build(copy)
for v, h in hashes.items():
    print(f"built by sdk {v}: {h}")
print("same package" if len(set(hashes.values())) == 1 else "DIFFERENT packages")
sys.exit(0)
