"""S2 harness: run the 40-task battery live, measure the go/no-go numbers.

Usage (from repo root, host — NOT pytest; live LLM calls are allowed here only):

    .venv/bin/python scripts/llm_harness.py [--no-db] [--limit N]

Measures:
- valid-call rate      = well-formed tool calls / all tool calls emitted
- loop-completion rate = tasks where every required tool ran validly AND the
                         final answer contains the expected evidence
Persists a scorecard row (workspace 'dev') and writes the raw run JSON next to
the probe docs. Verdict comes from decide_agent_mode — code, not vibes.
"""

import argparse
import asyncio
import json
import sys
import time
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from auspex.devhost import pin_host_defaults  # noqa: E402

pin_host_defaults()  # host-run script: .env hostnames are compose-internal

import httpx  # noqa: E402

from auspex.config import get_settings  # noqa: E402
from auspex.db import create_pool  # noqa: E402
from auspex.llm.capability import PROBE_MAX_TOKENS, probe_capabilities  # noqa: E402
from auspex.llm.client import LLMClient, LLMError, ToolCall  # noqa: E402
from auspex.llm.scorecard import decide_agent_mode, save_scorecard  # noqa: E402
from scripts.harness_tasks import SYSTEM_PROMPT, TASKS, TOOL_SPECS, Task, execute_tool  # noqa: E402


def validate_call(task: Task, call: ToolCall) -> tuple[dict | None, str]:
    """(parsed_args, "ok") for a VALID call — tool offered to this task, args
    parse to an object, required params present, enum values legal — else
    (None, reason)."""
    if call.name not in task.tools:
        return None, "unknown_tool"
    try:
        args = call.parse_arguments()
    except ValueError:
        return None, "unparseable_arguments"
    params = TOOL_SPECS[call.name]["function"]["parameters"]
    for required in params.get("required", []):
        if required not in args:
            return None, f"missing_required:{required}"
    for key, spec in params.get("properties", {}).items():
        if key in args and "enum" in spec and args[key] not in spec["enum"]:
            return None, f"bad_enum:{key}"
    return args, "ok"


async def run_task(client: LLMClient, task: Task) -> dict:
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": task.prompt},
    ]
    tools = [TOOL_SPECS[name] for name in dict.fromkeys(task.tools)]
    calls_made: list[str] = []
    violations: list[str] = []
    valid = invalid = 0
    final_answer = None
    steps = 0

    for _ in range(task.max_steps):
        steps += 1
        try:
            # Same thinking-model budget as the capability battery — the two
            # measurement paths must judge models on the same footing.
            result = await client.chat(
                messages, tools=tools, temperature=0, max_tokens=PROBE_MAX_TOKENS
            )
        except LLMError as err:
            return {"task": task.id, "category": task.category, "error": str(err),
                    "valid": valid, "invalid": invalid, "completed": False,
                    "violations": violations, "steps": steps}

        if not result.tool_calls:
            final_answer = result.content or ""
            break

        # replay shape proven by the roundtrip probe (finding 6)
        messages.append({
            "role": "assistant",
            "content": result.content or None,
            "tool_calls": [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.name, "arguments": tc.arguments}}
                for tc in result.tool_calls
            ],
        })
        for tc in result.tool_calls:
            args, why = validate_call(task, tc)
            if args is not None:
                valid += 1
                calls_made.append(tc.name)
                output = execute_tool(tc.name, args)
            else:
                invalid += 1
                violations.append(f"{tc.name or '<noname>'}:{why}")
                output = {"error": f"invalid call ({why})"}
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(output),
            })

    # completion: required tools all ran validly (multiset), evidence present,
    # no-tool tasks stayed tool-free, and the model actually answered.
    required_ok = not (Counter(task.required_calls) - Counter(calls_made))
    evidence_ok = final_answer is not None and all(
        s.lower() in final_answer.lower() for s in task.success_substrings
    )
    restraint_ok = not task.forbid_tool_calls or (valid + invalid == 0)
    completed = required_ok and evidence_ok and restraint_ok and invalid == 0

    return {
        "task": task.id, "category": task.category, "steps": steps,
        "valid": valid, "invalid": invalid, "violations": violations,
        "calls_made": calls_made, "completed": completed,
        "required_ok": required_ok, "evidence_ok": evidence_ok,
        "restraint_ok": restraint_ok,
        "final_answer": (final_answer or "")[:300],
    }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-db", action="store_true", help="skip the scorecard insert")
    parser.add_argument("--limit", type=int, default=0, help="run only the first N tasks")
    parser.add_argument("--model", default="", help="override LLM_MODEL for this run")
    cli = parser.parse_args()

    settings = get_settings()
    tasks = TASKS[: cli.limit] if cli.limit else TASKS

    client_ctx = LLMClient(
        settings.llm_base_url,
        cli.model or settings.llm_model,
        settings.llm_api_key,
    )
    async with client_ctx as client:
        ok, detail = await client.check_reachable()
        if not ok:
            print(f"endpoint unreachable ({detail}) — aborting, nothing measured")
            sys.exit(1)

        # provider-specific context hint (Ollama native API); generic code gets None
        max_ctx = None
        try:
            async with httpx.AsyncClient(timeout=10.0) as http:
                r = await http.post(f"{client.base_url}/api/show", json={"model": client.model})
                if r.status_code == 200:
                    info = r.json().get("model_info", {})
                    max_ctx = next(
                        (v for k, v in info.items() if k.endswith("context_length")), None
                    )
        except httpx.HTTPError:
            pass

        print("== capability battery ==")
        sc = await probe_capabilities(client, max_context_hint=max_ctx)
        dumped = sc.model_dump()
        for field_name, value in dumped.items():
            if field_name not in ("base_url", "model", "notes"):
                print(f"  {field_name}: {value}")
        if sc.notes:
            print(f"  notes: {sc.notes}")

        print(f"\n== harness: {len(tasks)} tasks ==")
        t0 = time.monotonic()
        results = []
        for task in tasks:
            outcome = await run_task(client, task)
            results.append(outcome)
            mark = "✓" if outcome["completed"] else "✗"
            extra = f" violations={outcome['violations']}" if outcome["violations"] else ""
            print(f"  {mark} {outcome['task']} ({outcome['category']}) steps={outcome['steps']}"
                  f" valid={outcome['valid']} invalid={outcome['invalid']}{extra}")
        wall = time.monotonic() - t0

        total_valid = sum(r["valid"] for r in results)
        total_invalid = sum(r["invalid"] for r in results)
        total_calls = total_valid + total_invalid
        completed = sum(1 for r in results if r["completed"])
        sc.valid_call_rate = round(total_valid / total_calls, 4) if total_calls else None
        sc.loop_completion_rate = round(completed / len(results), 4) if results else None

        by_cat: dict[str, list[dict]] = {}
        for r in results:
            by_cat.setdefault(r["category"], []).append(r)
        category_rates = {
            cat: round(sum(1 for r in rs if r["completed"]) / len(rs), 3)
            for cat, rs in sorted(by_cat.items())
        }

        mode = decide_agent_mode(sc)
        summary = {
            "endpoint": sc.base_url, "model": sc.model,
            "tasks": len(results), "tool_calls": total_calls,
            "valid_call_rate": sc.valid_call_rate,
            "loop_completion_rate": sc.loop_completion_rate,
            "per_category_completion": category_rates,
            "violations": Counter(v for r in results for v in r["violations"]),
            "wall_seconds": round(wall, 1),
            "agent_mode": mode,
        }
        print("\n== summary ==")
        for key, value in summary.items():
            print(f"  {key}: {value}")

        dumped["valid_call_rate"] = sc.valid_call_rate
        dumped["loop_completion_rate"] = sc.loop_completion_rate
        run_blob = {"summary": {**summary, "violations": dict(summary["violations"])},
                    "scorecard": dumped, "results": results}
        model_slug = "".join(c if c.isalnum() else "-" for c in client.model)
        out_path = REPO / "docs" / "probes" / f"harness-run-{model_slug}.json"
        out_path.write_text(json.dumps(run_blob, indent=2) + "\n")
        print(f"\nraw run -> {out_path.relative_to(REPO)}")

        if not cli.no_db:
            pool = await create_pool(settings.database_url, retries=2, delay=0.5)
            try:
                workspace_id = await pool.fetchval(
                    "INSERT INTO workspaces (name) VALUES ('dev')"
                    " ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name RETURNING id"
                )
                row_id = await save_scorecard(pool, workspace_id, sc)
                print(f"scorecard row {row_id} saved (workspace 'dev', mode={mode})")
            finally:
                await pool.close()

        print(f"\nVERDICT: agent runtime compiles to **{mode}** for this endpoint")


if __name__ == "__main__":
    asyncio.run(main())
