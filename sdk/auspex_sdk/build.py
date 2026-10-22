"""`auspex-sdk build`: Python-first or YAML source in, one manifest and one package out (S32).

D-064's promise: two authoring formats, one canonical form. A source directory holds either

  * `connector.yaml` plus the Python handler modules it names (the YAML form), or
  * one top-level module that defines the `@connector` class (the Python-first form).

The YAML mirrors `manifest.json` key for key and nesting for nesting, minus `sdk_version`
(the build fills it); handler references are `module:function` relative to the source dir.
Both forms end as the same `Manifest` dataclass, so `manifest_to_json` gives the same bytes.

The build imports the author's modules. That is allowed here: this is the SDK on the author's
own machine, never the core. Each import runs with the source dir on `sys.path` for the span
of one step only, and every module it loaded from that dir is dropped from `sys.modules`
afterwards, so a build leaves no trace and two builds in one process cannot see each other.

`check_handlers` imports each referenced module and refuses a missing module or function by its
reference, and a parameter mismatch: a handler takes the context first and then exactly the
action's declared param names, in order (an author cannot forget one); `test` takes `(ctx)`;
`fetch` takes `(ctx, cursor, limit)`. The same rule covers an action's `execute`.

`build` writes `dist/<id>-<version>.zip` in the source dir and verifies the bytes with
`read_package`, so a build can never produce something the catalogue would refuse.
"""

import dataclasses
import importlib
import importlib.metadata
import inspect
import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType

import yaml

from auspex_sdk.manifest import (
    Manifest,
    manifest_to_json,
    parse_manifest,
    validate_manifest,
)
from auspex_sdk.package import MANIFEST_NAME, build_zip, read_package
from auspex_sdk.runtime import _ConnectorSpec, _spec_of, collect

YAML_NAME = "connector.yaml"
DIST_DIR = "dist"

# What `read_package` refuses, so the build leaves it out instead of failing on it.
_EXCLUDED_DIRS = frozenset({"tests", "test", "__pycache__", DIST_DIR})


class BuildError(ValueError):
    """The source directory cannot be built. The message names what and where."""


def sdk_version() -> str:
    try:
        return importlib.metadata.version("auspex-sdk")
    except importlib.metadata.PackageNotFoundError:
        return "0+unknown"


# --- importing the author's code ---------------------------------------------------------------


def _under(path: str | None, root: Path) -> bool:
    if not path:
        return False
    try:
        Path(path).resolve().relative_to(root)
    except ValueError:
        return False
    return True


@contextmanager
def importable(source_dir: Path) -> Iterator[None]:
    root = source_dir.resolve()
    before = set(sys.modules)
    dont_write = sys.dont_write_bytecode
    sys.dont_write_bytecode = True  # a build must not litter the source dir with caches
    sys.path.insert(0, str(root))
    importlib.invalidate_caches()
    try:
        yield
    finally:
        sys.dont_write_bytecode = dont_write
        try:
            sys.path.remove(str(root))
        except ValueError:
            pass
        for name in set(sys.modules) - before:
            if _under(getattr(sys.modules[name], "__file__", None), root):
                del sys.modules[name]
        importlib.invalidate_caches()


def import_source_module(name: str, root: Path, where: str) -> ModuleType:
    try:
        mod = importlib.import_module(name)
    except ModuleNotFoundError as e:
        if e.name and (name == e.name or name.startswith(e.name + ".")):
            raise BuildError(f"{where}: module {name!r} not found in the source directory") from e
        raise BuildError(f"{where}: importing {name!r} failed: {e}") from e
    except KeyboardInterrupt:
        raise
    except BaseException as e:  # author code ran; even a sys.exit() at import is a refusal
        raise BuildError(f"{where}: importing {name!r} failed: {type(e).__name__}: {e}") from e
    if not _under(getattr(mod, "__file__", None), root):
        raise BuildError(f"{where}: module {name!r} does not come from the source directory")
    return mod


# --- handler checks ---------------------------------------------------------------------------


def _handler_refs(m: Manifest) -> list[tuple[str, str, tuple[str, ...]]]:
    """(manifest path, reference, the parameter names after ctx it must take)."""
    refs = [("commands.test.handler", m.test_handler, ())]
    if m.fetch is not None:
        refs.append(("commands.fetch.handler", m.fetch.handler, ("cursor", "limit")))
    for i, a in enumerate(m.actions):
        names = tuple(p.name for p in a.params)
        refs.append((f"actions[{i}].execute", a.execute, names))
        refs.append((f"actions[{i}].dry_run", a.dry_run, names))
        if a.undo is not None:
            refs.append((f"actions[{i}].undo.handler", a.undo.handler, names))
        if a.observe is not None:
            refs.append((f"actions[{i}].observe", a.observe, names))
    return refs


def _check_signature(fn: object, where: str, ref: str, want: tuple[str, ...]) -> None:
    try:
        params = list(inspect.signature(fn).parameters.values())  # type: ignore[arg-type]
    except (TypeError, ValueError) as e:
        raise BuildError(f"{where}: handler {ref!r} has no readable signature") from e
    first_ok = params and params[0].kind in (
        inspect.Parameter.POSITIONAL_ONLY,
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
    )
    rest = params[1:]
    named = all(
        p.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
        for p in rest
    )
    got = tuple(p.name for p in rest)
    if not first_ok or not named or got != want:
        shown = ", ".join(("ctx", *want))
        raise BuildError(
            f"{where}: handler {ref!r} must take ({shown}) and nothing else, "
            f"as the manifest declares; it takes {inspect.signature(fn)}"  # type: ignore[arg-type]
        )


def check_handlers(manifest: Manifest, source_dir: Path) -> None:
    """Refuse a handler that is missing, or whose parameters differ from the declaration."""
    root = Path(source_dir).resolve()
    with importable(root):
        for where, ref, want in _handler_refs(manifest):
            module_name, _, func_name = ref.partition(":")
            mod = import_source_module(module_name, root, where)
            fn = getattr(mod, func_name, None)
            if not callable(fn):
                raise BuildError(
                    f"{where}: handler {ref!r}: {func_name!r} is not in {module_name!r}"
                )
            _check_signature(fn, where, ref, want)


# --- the two source forms --------------------------------------------------------------------


class _UniqueKeyLoader(yaml.SafeLoader):
    """SafeLoader that refuses a repeated key (plain safe_load keeps the last, silently)."""


def _no_duplicates(loader: yaml.SafeLoader, node: yaml.MappingNode, deep: bool = False) -> dict:
    seen: set = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in seen:
            raise yaml.constructor.ConstructorError(
                None, None, f"duplicate key {key!r}", key_node.start_mark
            )
        seen.add(key)
    return yaml.SafeLoader.construct_mapping(loader, node, deep=deep)


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    lambda loader, node: _no_duplicates(loader, node, deep=True),
)


def _manifest_from_yaml(path: Path) -> Manifest:
    try:
        data = yaml.load(path.read_text(encoding="utf-8"), Loader=_UniqueKeyLoader)  # noqa: S506
    except (yaml.YAMLError, UnicodeDecodeError) as e:
        raise BuildError(f"{YAML_NAME} is not valid YAML: {' '.join(str(e).split())}") from e
    if not isinstance(data, dict):
        raise BuildError(f"{YAML_NAME} must be a mapping shaped like manifest.json")
    if "sdk_version" in data:
        raise BuildError(f"{YAML_NAME}: sdk_version is filled in by the build; remove it")
    data["sdk_version"] = sdk_version()
    m = parse_manifest(data)
    validate_manifest(m)
    return m


def _manifest_from_python(source_dir: Path) -> Manifest:
    root = source_dir.resolve()
    candidates = sorted(
        p.name
        for p in root.glob("*.py")
        if p.is_file()
        and not p.name.startswith(("test_", ".", "__"))
        and p.name not in ("setup.py", "conftest.py")
    )
    found: list[tuple[str, ModuleType]] = []
    with importable(root):
        for fname in candidates:
            name = fname[:-3]
            mod = import_source_module(name, root, fname)
            if any(
                isinstance(_spec_of(o), _ConnectorSpec)
                and getattr(o, "__module__", None) == mod.__name__
                for o in vars(mod).values()
            ):
                found.append((name, mod))
        if not found:
            raise BuildError(f"no {YAML_NAME} and no top-level module with a @connector class")
        if len(found) > 1:
            names = ", ".join(n + ".py" for n, _ in found)
            raise BuildError(f"more than one module defines a @connector: {names}")
        m = collect(found[0][1])
    return dataclasses.replace(m, sdk_version=sdk_version())


def load_manifest(source_dir: Path) -> Manifest:
    """The validated manifest of a source dir, from connector.yaml or from the decorators."""
    source_dir = Path(source_dir)
    if not source_dir.is_dir():
        raise BuildError(f"{source_dir} is not a directory")
    yaml_path = source_dir / YAML_NAME
    if yaml_path.is_file():
        return _manifest_from_yaml(yaml_path)
    return _manifest_from_python(source_dir)


# --- the package -----------------------------------------------------------------------------


def _excluded_dir(name: str) -> bool:
    return name.startswith(".") or name.casefold() in _EXCLUDED_DIRS


def _excluded_file(name: str) -> bool:
    low = name.casefold()
    return (
        name.startswith(".")
        or low.endswith((".pyc", ".yaml", ".yml"))
        or (low.startswith("test_") and low.endswith(".py"))
    )


def _collect_files(root: Path) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        here = Path(dirpath)
        for d in list(dirnames):
            if _excluded_dir(d):
                dirnames.remove(d)
            elif (here / d).is_symlink():
                raise BuildError(f"{(here / d).relative_to(root).as_posix()}: symlinks are refused")
        dirnames.sort()
        for f in sorted(filenames):
            if _excluded_file(f):
                continue
            p = here / f
            rel = p.relative_to(root).as_posix()
            if p.is_symlink():
                raise BuildError(f"{rel}: symlinks are refused")
            if rel == MANIFEST_NAME:
                raise BuildError(f"{rel}: the build writes manifest.json; remove yours")
            files[rel] = p.read_bytes()
    return files


def build(source_dir: Path) -> tuple[Path, str]:
    """Build `dist/<id>-<version>.zip` in the source dir; return (zip path, content hash)."""
    source_dir = Path(source_dir)
    manifest = load_manifest(source_dir)
    check_handlers(manifest, source_dir)
    files = _collect_files(source_dir.resolve())
    files[MANIFEST_NAME] = manifest_to_json(manifest)
    data = build_zip(files)
    _, digest, _ = read_package(data)  # whatever the catalogue would refuse, refuse here
    out = source_dir / DIST_DIR / f"{manifest.id}-{manifest.version}.zip"
    out.parent.mkdir(exist_ok=True)
    out.write_bytes(data)
    return out, digest
