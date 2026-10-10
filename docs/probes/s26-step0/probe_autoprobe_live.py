"""S26 — D-038 live: the startup probe's own code against a real, unmeasured endpoint.

The container's startup probe found the dev endpoint already measured
("known", nothing spent). This runs the same `autoprobe` — real
`probe_capabilities`, real client — from the host against a fingerprint nobody
has measured: glm-5.3-flash on the same Z.ai general API (D-034's
cheapest-but-viable candidate). It is a real measurement and is kept: if
LLM_MODEL ever moves to that model, its deployment scorecard is already true.

~15 requests. Run:  .venv/bin/python docs/probes/s26-step0/probe_autoprobe_live.py
"""

import asyncio
import sys
import time

sys.path.insert(0, "/home/burhan/auspex-new")

from auspex.devhost import pin_host_defaults  # noqa: E402

pin_host_defaults()

from auspex.config import Settings  # noqa: E402
from auspex.db import create_pool  # noqa: E402
from auspex.llm.autoprobe import autoprobe  # noqa: E402
from auspex.llm.scorecard import load_deployment_scorecard  # noqa: E402

MODEL = "glm-5.3-flash"


async def main() -> None:
    settings = Settings().model_copy(update={"llm_model": MODEL})
    pool = await create_pool(settings.database_url)
    try:
        before = await load_deployment_scorecard(pool, settings.llm_base_url, MODEL)
        print(f"before: {'scorecard exists' if before else 'no scorecard'}")
        t0 = time.monotonic()
        outcome = await autoprobe(pool, settings, delays=())
        print(f"first attempt: {outcome}  ({time.monotonic() - t0:.0f}s)")
        loaded = await load_deployment_scorecard(pool, settings.llm_base_url, MODEL)
        if loaded:
            sc, mode = loaded
            print(f"recorded: agent_mode={mode} native_reasoning={sc.native_reasoning} "
                  f"native_tool_calling={sc.native_tool_calling} "
                  f"streaming_tool_deltas={sc.streaming_tool_deltas} "
                  f"parallel={sc.parallel_tool_calls} tok/s={sc.tokens_per_second}")
            print(f"notes: {len(sc.notes)}")
        t1 = time.monotonic()
        again = await autoprobe(pool, settings, delays=())
        print(f"second attempt: {again}  ({time.monotonic() - t1:.1f}s) — once per fingerprint")
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
