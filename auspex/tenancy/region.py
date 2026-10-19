"""Residency as a refusal (D-061; S30 design §4).

Each workspace carries a region; the deployment's engine processes in one
(`ENGINE_REGION`), it stores its data in one (`STORAGE_REGION`, D-069), and each
enrichment provider declares its own in code. A
`global` workspace carries no residency constraint, so anything may serve it;
any other region is served only from inside itself. Stdlib only: `auspex.config`
imports this module.
"""

GLOBAL = "global"
# A new region is a code change, reviewed, never a row someone inserts. The
# workspaces.region CHECK (auspex/migrations.py) holds the same list, and a
# test pins that the two agree.
REGIONS: frozenset[str] = frozenset({GLOBAL, "ksa"})


def check_region(region: str) -> str:
    if region not in REGIONS:
        raise ValueError(f"unknown region {region!r}; known regions: {', '.join(sorted(REGIONS))}")
    return region


def may_process(workspace_region: str, processor_region: str) -> bool:
    """Whether a processor in `processor_region` may handle the data of a
    workspace in `workspace_region`. An unknown region is an error, never a yes."""
    check_region(workspace_region)
    check_region(processor_region)
    return workspace_region == GLOBAL or workspace_region == processor_region


def engine_refusal(workspace_region: str, engine_region: str) -> str | None:
    """The reason an engine turn is refused, or None when the engine may serve it."""
    if may_process(workspace_region, engine_region):
        return None
    return (
        f"This workspace's data must stay in region {workspace_region}, and the "
        f"platform's engine here processes in region {engine_region}, so it cannot "
        "run this request. Answers that need no engine still work."
    )


def storage_refusal(workspace_region: str, storage_region: str) -> str | None:
    """The reason a workspace cannot be made on this deployment (D-069), or None.
    Storing is processing at rest: the same rule as `may_process`."""
    if may_process(workspace_region, storage_region):
        return None
    return (
        f"A workspace whose data must stay in region {workspace_region} cannot be "
        f"created here: this deployment stores its data in region {storage_region} "
        "(STORAGE_REGION)."
    )


def region_skip(region: str) -> str:
    """The skip reason an indicator carries when no allowed source exists."""
    return (
        "not looked up: every connected source processes outside this "
        f"workspace's region ({region})"
    )


def lookup_refusal(region: str) -> str:
    return (
        "Third-party lookups are not available in this workspace's region "
        f"({region}): every connected source processes outside it."
    )
