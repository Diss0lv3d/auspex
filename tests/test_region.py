"""S30 (D-061): residency is a refusal. One rule, a closed vocabulary."""

import pytest

from auspex.config import Settings
from auspex.tenancy.region import (
    REGIONS,
    engine_refusal,
    lookup_refusal,
    may_process,
    region_skip,
)


def test_the_vocabulary_is_closed():
    assert REGIONS == frozenset({"global", "ksa"})


@pytest.mark.parametrize(
    ("workspace", "processor", "allowed"),
    [
        ("global", "global", True),
        ("global", "ksa", True),
        ("ksa", "ksa", True),
        ("ksa", "global", False),
    ],
)
def test_a_processor_serves_global_workspaces_and_its_own_region(workspace, processor, allowed):
    assert may_process(workspace, processor) is allowed


@pytest.mark.parametrize(
    "pair", [("eu", "global"), ("global", "eu"), ("", "global"), ("KSA", "ksa")]
)
def test_an_unknown_region_is_an_error_never_a_yes(pair):
    with pytest.raises(ValueError, match="unknown region"):
        may_process(*pair)


def test_the_engine_refusal_names_both_regions_and_no_vendor():
    text = engine_refusal("ksa", "global")
    assert "ksa" in text and "global" in text
    assert "the platform's engine" in text
    assert engine_refusal("ksa", "ksa") is None
    assert engine_refusal("global", "global") is None
    assert engine_refusal("global", "ksa") is None


def test_the_lookup_copy_names_the_region():
    assert "ksa" in region_skip("ksa")
    assert "ksa" in lookup_refusal("ksa")


def test_engine_region_defaults_to_global(monkeypatch):
    monkeypatch.delenv("ENGINE_REGION", raising=False)
    assert Settings(_env_file=None).engine_region == "global"


def test_an_unknown_engine_region_stops_startup(monkeypatch):
    monkeypatch.setenv("ENGINE_REGION", "mars")
    with pytest.raises(RuntimeError, match="ENGINE_REGION"):
        Settings(_env_file=None)
