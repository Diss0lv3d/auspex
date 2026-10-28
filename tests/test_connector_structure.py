"""Nothing a connector ships runs in the app process (S32, D-062): pinned by reading
the core's source, so a stray import fails here before it can ship."""

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CORE = ROOT / "auspex"
CONNECTORS = CORE / "connectors"

# The SDK's pure modules (manifest, vocab, package) are allowed; these run author code
# or parse YAML.
FORBIDDEN_IMPORTS = ("yaml", "auspex_sdk.build", "auspex_sdk.harness", "auspex_sdk.runtime",
                     "auspex_sdk.http", "auspex_sdk.cli", "examples")
FORBIDDEN_CALLS = ("importlib", "exec", "eval", "zipimport", "__import__")


def _modules(base: Path) -> list[Path]:
    return sorted(base.rglob("*.py"))


def _imports(tree: ast.AST) -> set[str]:
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{a.name}" for a in node.names)
    return names


def _forbidden(name: str) -> bool:
    return any(name == f or name.startswith(f + ".") for f in FORBIDDEN_IMPORTS)


def _offences(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    return sorted(n for n in _imports(tree) if _forbidden(n))


def _calls(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    found = set()
    for name in _imports(tree):
        if name.split(".")[0] in FORBIDDEN_CALLS:
            found.add(name)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id in FORBIDDEN_CALLS:
            found.add(node.func.id + "(")
    return sorted(found)


def test_the_core_imports_no_connector_code_or_yaml():
    offences = {str(p.relative_to(ROOT)): o for p in _modules(CORE) if (o := _offences(p))}
    assert offences == {}


def test_the_connectors_package_never_loads_code_dynamically():
    offences = {str(p.relative_to(ROOT)): c for p in _modules(CONNECTORS) if (c := _calls(p))}
    assert offences == {}


@pytest.mark.parametrize("line", ["import yaml", "from auspex_sdk.runtime import connector",
                                  "import examples.connectors"])
def test_the_import_check_catches_a_mutant(tmp_path, line):
    mutant = tmp_path / "catalogue.py"
    mutant.write_text((CONNECTORS / "catalogue.py").read_text() + f"\n{line}\n")
    assert _offences(mutant)


@pytest.mark.parametrize("line", ["import importlib", "exec('x')", "eval('1')",
                                  "import zipimport"])
def test_the_dynamic_load_check_catches_a_mutant(tmp_path, line):
    mutant = tmp_path / "compile.py"
    mutant.write_text((CONNECTORS / "compile.py").read_text() + f"\n{line}\n")
    assert _calls(mutant)


def test_the_shared_validators_import_only_the_manifest():
    """S33: the core checks what an Edge Agent posts with `auspex_sdk.validate`, so it
    must stay pure: the SDK's manifest and the stdlib, never runtime, build or harness."""
    import auspex_sdk.validate as v

    tree = ast.parse(Path(v.__file__).read_text())
    sdk = {n for n in _imports(tree) if n.startswith("auspex_sdk")}
    assert sdk <= {"auspex_sdk.manifest"} | {f"auspex_sdk.manifest.{x}" for x in
                                             ("Action", "Manifest", "ManifestError",
                                              "check_fetch_item")}, sdk
