"""Agent runtime (S3): tool registry, permission gate, ReACT loop.

The loop is capability-negotiated — it runs in the mode the capability probe
persisted for the endpoint (native_tools / prompted_tools / plan_only), never
re-deriving it at call time (thresholds may have drifted since the probe).
Safety-critical behaviour (writes gate on real execution, D-014) lives in code
here, never in a prompt (ADR: code over prompts).
"""
