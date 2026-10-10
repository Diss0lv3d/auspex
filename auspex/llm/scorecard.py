"""Typed capability scorecard for a customer LLM endpoint (D-005).

The scorecard is the contract between the capability probe and the agent
runtime: the probe fills it, `decide_agent_mode` compiles it to a runtime mode
(native tools → prompted tools → plan-only). Thresholds live HERE, in code —
never in a prompt (ADR: code over prompts for safety-critical behaviour).
"""

import hashlib
import json

import asyncpg
from pydantic import BaseModel, Field

# Mode thresholds. Sources: S2 harness measures valid-call rate (well-formed
# tool calls / all tool calls) and loop-completion rate (multi-step tasks fully
# completed). Below these, native tool-calling hurts more than it helps.
NATIVE_MIN_VALID_CALL_RATE = 0.85
NATIVE_MIN_LOOP_COMPLETION_RATE = 0.70
PROMPTED_MIN_SCHEMA_ADHERENCE = 0.80

AgentMode = str  # 'native_tools' | 'prompted_tools' | 'plan_only'


class CapabilityScorecard(BaseModel):
    """What one live endpoint actually supports, as measured — never assumed."""

    base_url: str
    model: str

    reachable: bool = False
    native_reasoning: bool = False  # emits thinking on its own field (thinking model)
    native_tool_calling: bool = False
    parallel_tool_calls: bool = False
    tool_choice_named: bool = False  # tool_choice={"type":"function",...} honored
    tool_choice_required: bool = False  # tool_choice="required" honored
    tool_role_roundtrip: bool = False  # accepts assistant tool_calls + role:"tool" replay
    streaming: bool = False
    streaming_tool_deltas: bool = False
    usage_in_stream: bool = False  # stream_options.include_usage honored
    json_object_mode: bool = False  # response_format {"type": "json_object"}
    json_schema_mode: bool = False  # response_format {"type": "json_schema", ...}

    schema_adherence_rate: float | None = None  # battery: valid-JSON-per-schema rate
    valid_call_rate: float | None = None  # harness: well-formed tool calls / all calls
    loop_completion_rate: float | None = None  # harness: fully completed multi-step tasks
    max_context_tokens: int | None = None
    tokens_per_second: float | None = None

    notes: list[str] = Field(default_factory=list)


def endpoint_fingerprint(base_url: str, model: str) -> str:
    """Stable endpoint identity WITHOUT the API key — safe to store and index."""
    return hashlib.sha256(f"{base_url.rstrip('/')}|{model}".encode()).hexdigest()


def decide_agent_mode(sc: CapabilityScorecard) -> AgentMode:
    """Compile the scorecard to a runtime mode. Unmeasured rates don't demote:
    a fresh connect-time probe (no harness numbers yet) trusts native support,
    and the first harness run corrects it."""
    if not sc.reachable:
        return "plan_only"
    if (
        sc.native_tool_calling
        and (sc.valid_call_rate is None or sc.valid_call_rate >= NATIVE_MIN_VALID_CALL_RATE)
        and (
            sc.loop_completion_rate is None
            or sc.loop_completion_rate >= NATIVE_MIN_LOOP_COMPLETION_RATE
        )
    ):
        return "native_tools"
    if sc.json_object_mode or (sc.schema_adherence_rate or 0.0) >= PROMPTED_MIN_SCHEMA_ADHERENCE:
        return "prompted_tools"
    return "plan_only"


async def save_scorecard(
    pool: asyncpg.Pool, workspace_id: str, sc: CapabilityScorecard
) -> str:
    """Insert one probe run; history is kept (newest wins via probed_at DESC)."""
    return await pool.fetchval(
        """
        INSERT INTO llm_endpoint_scorecards
            (workspace_id, endpoint_fingerprint, base_url, model, agent_mode, scorecard)
        VALUES ($1, $2, $3, $4, $5, $6)
        RETURNING id
        """,
        workspace_id,
        endpoint_fingerprint(sc.base_url, sc.model),
        sc.base_url,
        sc.model,
        decide_agent_mode(sc),
        json.dumps(sc.model_dump()),
    )


async def load_latest_scorecard(
    pool: asyncpg.Pool, workspace_id: str, base_url: str, model: str
) -> tuple[CapabilityScorecard, AgentMode] | None:
    row = await pool.fetchrow(
        """
        SELECT scorecard, agent_mode FROM llm_endpoint_scorecards
        WHERE workspace_id = $1 AND endpoint_fingerprint = $2
        ORDER BY probed_at DESC
        LIMIT 1
        """,
        workspace_id,
        endpoint_fingerprint(base_url, model),
    )
    if row is None:
        return None
    return CapabilityScorecard(**json.loads(row["scorecard"])), row["agent_mode"]


# The default endpoint is configured per DEPLOYMENT (LLM_BASE_URL / LLM_MODEL),
# not per workspace, so its scorecard is deployment-scoped too (D-035): it lives
# in this one reserved system workspace. D-008 holds — the row still carries a
# workspace_id — and no analyst request ever reads ANOTHER TENANT's workspace:
# it reads this one, which no user can be provisioned into (auth.get_or_create_user
# refuses the name). Before D-035 the only writer (the harness) wrote to a
# workspace called 'dev' while the only reader read the analyst's, so the
# default endpoint never found its own scorecard.
DEPLOYMENT_WORKSPACE = "__deployment__"


async def save_deployment_scorecard(pool: asyncpg.Pool, sc: CapabilityScorecard) -> str:
    """Record a probe of the deployment's configured endpoint (D-035)."""
    workspace_id = await pool.fetchval(
        "INSERT INTO workspaces (name) VALUES ($1)"
        " ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name RETURNING id",
        DEPLOYMENT_WORKSPACE,
    )
    return await save_scorecard(pool, workspace_id, sc)


async def load_deployment_scorecard(
    pool: asyncpg.Pool, base_url: str, model: str
) -> tuple[CapabilityScorecard, AgentMode] | None:
    """The newest probe of the deployment's configured endpoint, or None if it
    has never been probed — which the caller must treat as unknown, not as no."""
    workspace_id = await pool.fetchval(
        "SELECT id FROM workspaces WHERE name = $1", DEPLOYMENT_WORKSPACE
    )
    if workspace_id is None:
        return None
    return await load_latest_scorecard(pool, workspace_id, base_url, model)
