"""Flattening for untrusted text that must enter a SYSTEM-role directive.

Parsed fields (an alert's rule name, an email's subject or display name) are
attacker-authored prose. Whenever a code-owned directive embeds one, it goes
through `flatten()` first: whitespace/control/invisible-unicode runs collapse
to a single space (so injected text can't open a fresh "directive" on its own
line, and zero-width/RLO tricks don't survive) and length is hard-capped (so a
field can't crowd out the instructions around it). Born in the S10 review
(finding B); shared here because the S11 phishing directive embeds the same
kind of field.
"""

from __future__ import annotations

import re

# \s (unicode-aware) + C0/DEL + the invisible-unicode ranges phishing headers
# use for obfuscation (ZWSP..RLM, LS/PS..RLO block, invisible operators, BOM).
_UNSAFE_RUN_RE = re.compile(
    r"[\s\x00-\x1f\x7f\u200b-\u200f\u2028-\u202f\u205f-\u206f\ufeff]+"
)


def flatten(raw: str, cap: int = 120) -> str:
    """Collapse whitespace/control runs to one space, strip, hard-cap length."""
    flat = _UNSAFE_RUN_RE.sub(" ", raw).strip()
    return flat[: cap - 1] + "…" if len(flat) > cap else flat
