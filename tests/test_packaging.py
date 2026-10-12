"""Packaging invariants — the container ships what the source tree contains.

`pyproject.toml` enumerates `[tool.setuptools] packages` by hand, and the
Dockerfile mirrors that list as a skeleton so the deps-only layer can build
metadata with no real source present. Two hand-maintained lists that must track a
directory tree, with nothing checking them.

S14 walked straight into it: `auspex/retrohunt` was added, both lists were not,
and the container installed an `auspex.enrich.store` that imports
`auspex.retrohunt.flips` alongside no `auspex/retrohunt` at all —
`ModuleNotFoundError` on any import from outside the source root.

It survived a green `./ci.sh` because the app runs `uvicorn server:app` with
WORKDIR=/srv/auspex, where the COPY'd source shadows site-packages on sys.path;
the liveness probe therefore passed while the INSTALLED distribution was broken.
Caught only by running a script from /tmp inside the container. These tests are
that accident turned into a gate.
"""

import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_ROOT = REPO_ROOT / "auspex"


def _declared_packages() -> set[str]:
    with (REPO_ROOT / "pyproject.toml").open("rb") as fh:
        return set(tomllib.load(fh)["tool"]["setuptools"]["packages"])


def _actual_packages() -> set[str]:
    """Every importable package under auspex/ — a directory with __init__.py."""
    found = {"auspex"}
    for init in PACKAGE_ROOT.rglob("__init__.py"):
        rel = init.parent.relative_to(REPO_ROOT)
        if "__pycache__" in rel.parts:
            continue
        found.add(".".join(rel.parts))
    return found


def test_every_source_package_is_declared_for_install():
    """A package missing here is absent from the installed distribution: the
    module imports fine in the source tree and in tests, and fails in the
    container."""
    missing = _actual_packages() - _declared_packages()
    assert not missing, (
        f"packages present in the source tree but NOT in pyproject "
        f"[tool.setuptools] packages: {sorted(missing)}. Add them there AND to "
        f"the Dockerfile skeleton, or the container ships a broken install."
    )


def test_no_declared_package_is_missing_from_the_source_tree():
    """The other direction: a stale entry makes `pip install .` fail outright."""
    stale = _declared_packages() - _actual_packages()
    assert not stale, f"declared but absent from the source tree: {sorted(stale)}"


def test_dockerfile_skeleton_covers_every_declared_package():
    """The deps-only layer builds metadata against a skeleton, so setuptools must
    find a directory for every declared package. A missing skeleton entry breaks
    the image BUILD (loudly) rather than the install (quietly) — still worth
    pinning, since the two lists have no other connection."""
    dockerfile = (REPO_ROOT / "Dockerfile").read_text()
    skeleton = dockerfile.split("# App layer")[0]
    for package in sorted(_declared_packages()):
        path = package.replace(".", "/")
        assert f"{path}/__init__.py" in skeleton or path == "auspex", (
            f"{package} is declared in pyproject but has no `touch "
            f"{path}/__init__.py` in the Dockerfile's deps-only skeleton layer"
        )


def test_dockerfile_does_not_carry_stale_build_artifacts_into_the_wheel():
    """The deps-only layer runs `pip install .` against a SKELETON, which leaves
    `build/lib/auspex/**/__init__.py` at 0 bytes. setuptools reuses build/lib and
    skips files whose timestamps look current, so the app layer's wheel inherited
    those empty files: every __init__.py in the installed distribution was 0 bytes
    for every package, from the day this Dockerfile was written until S14.

    It never failed anything, because uvicorn runs with WORKDIR on sys.path and
    the COPY'd source shadowed site-packages — the app served correctly on top of
    a broken install. Both layers must clean up after themselves."""
    dockerfile = (REPO_ROOT / "Dockerfile").read_text()
    deps_layer, _, app_layer = dockerfile.partition("# App layer")
    assert "rm -rf" in deps_layer and "build" in deps_layer.split("rm -rf")[1], (
        "the deps-only layer must delete `build` (and auspex.egg-info) after its "
        "skeleton install, or the app layer's wheel reuses the empty skeleton files"
    )
    assert "build" in app_layer.split("rm -rf")[-1], (
        "the app layer must delete `build` too, so a rebuilt image never reuses "
        "this image's artifacts"
    )


def test_build_artifacts_are_excluded_from_the_docker_context():
    """Belt and braces for the same failure from the other direction: a `build/`
    on the HOST (left by any local wheel build) must not be COPY'd into the image
    where setuptools would reuse it."""
    ignored = (REPO_ROOT / ".dockerignore").read_text().split()
    assert "build/" in ignored
    assert "*.egg-info/" in ignored


def test_the_pages_files_are_packaged():
    """TD-045: the chat page's CSS and modules ship in the wheel, and the
    deps-only skeleton satisfies their globs the way it does static/*.html."""
    pyproject = (REPO_ROOT / "pyproject.toml").read_text()
    assert '"static/css/*.css"' in pyproject and '"static/js/*.js"' in pyproject
    skeleton = (REPO_ROOT / "Dockerfile").read_text().split("# App layer")[0]
    assert "auspex/static/css/placeholder.css" in skeleton
    assert "auspex/static/js/placeholder.js" in skeleton
