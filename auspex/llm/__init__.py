"""LLM provider layer (S2): OpenAI-compatible client + capability scorecard.

The customer supplies the endpoint (D-005); we probe it and compile the agent
runtime to what the model can actually do. Code picks the mode, never a prompt.
"""

from auspex.llm.scorecard import CapabilityScorecard, decide_agent_mode, endpoint_fingerprint

__all__ = [
    "CapabilityScorecard",
    "decide_agent_mode",
    "endpoint_fingerprint",
]
