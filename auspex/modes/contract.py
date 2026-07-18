"""Typed output contracts for the DEEP path — S9 (ADR 0007 spirit: specs over
prompts). A contract is the single source of truth for a mode's output shape; it
COMPILES to (a) the system-prompt directive that instructs the model, and (b)
the validator that checks the model actually produced it. We never hand-write
the prompt and validator separately and hope they agree — the spec generates
both, so they cannot drift.

Contracts describe named sections of the analyst answer (plain text, `## Name`
headers — the chat UI renders verbatim). A field may be an enum (a closed set of
allowed values, e.g. a risk level); the validator enforces membership in code,
never by trusting the model (ADR 0006 spirit: code owns correctness).
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ContractField:
    """One required-or-optional section of a mode's output."""

    name: str  # section header, e.g. "Risk"
    description: str  # what the section must contain — drives the prompt
    required: bool = True
    # A closed value set (enum). Empty ⇒ free text. When set, the validator
    # checks the section's leading token is one of these (case-insensitive).
    allowed_values: tuple[str, ...] = ()


@dataclass(frozen=True)
class ModeContract:
    """A mode's typed output contract. `purpose` and `fields` compile to the
    system directive; `fields` + `rules` compile to the validator."""

    name: str  # the mode value (matches Mode enum), e.g. "alert_triage"
    purpose: str  # one-line role, opens the system directive
    fields: tuple[ContractField, ...]
    # Extra hard rules injected verbatim into the prompt AND surfaced to the
    # reader of the contract (e.g. alert_triage's "no data ≠ low risk").
    rules: tuple[str, ...] = ()

    def system_directive(self) -> str:
        """Compile the contract → a system-prompt fragment (specs → prompts)."""
        lines = [
            f"You are operating in {self.name} mode: {self.purpose}",
            "",
            "Structure your answer with these plain-text sections, each opened "
            'by a "## <Name>" header, in this order:',
        ]
        for f in self.fields:
            opt = "" if f.required else " (optional — omit if not applicable)"
            line = f"## {f.name}{opt} — {f.description}"
            if f.allowed_values:
                line += f" Must be exactly one of: {', '.join(f.allowed_values)}."
            lines.append(line)
        if self.rules:
            lines.append("")
            lines.append("Hard rules (these override any instinct to fill gaps):")
            lines.extend(f"- {r}" for r in self.rules)
        return "\n".join(lines)

    def validate(self, answer: str) -> ContractResult:
        """Validate a produced answer against the contract (specs → validators).
        Structural + enum checks only — never a semantic judgement of quality."""
        present = _sections(answer)
        missing: list[str] = []
        bad_enum: list[str] = []
        for f in self.fields:
            body = present.get(f.name.lower())
            if body is None:
                if f.required:
                    missing.append(f.name)
                continue
            if f.allowed_values:
                token = _leading_token(body)
                allowed = {v.lower() for v in f.allowed_values}
                if token.lower() not in allowed:
                    bad_enum.append(f"{f.name}={token or '∅'}")
        return ContractResult(
            mode=self.name, missing=tuple(missing), bad_enum=tuple(bad_enum)
        )


@dataclass(frozen=True)
class ContractResult:
    mode: str
    missing: tuple[str, ...] = ()  # required sections absent
    bad_enum: tuple[str, ...] = ()  # enum fields with an out-of-set value

    @property
    def ok(self) -> bool:
        return not self.missing and not self.bad_enum

    def reason(self) -> str:
        parts = []
        if self.missing:
            parts.append(f"missing sections: {', '.join(self.missing)}")
        if self.bad_enum:
            parts.append(f"out-of-contract values: {', '.join(self.bad_enum)}")
        return "; ".join(parts) or "ok"


_SECTION_RE = re.compile(r"^#{1,6}\s*(.+?)\s*$", re.MULTILINE)


def _sections(answer: str) -> dict[str, str]:
    """Split an answer into {header-lowercased: body}. A header is a markdown
    ATX heading line; matching is case-insensitive and tolerant of a leading
    enum token being on the header line or the body."""
    out: dict[str, str] = {}
    matches = list(_SECTION_RE.finditer(answer))
    for i, m in enumerate(matches):
        header = m.group(1).strip().lower()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(answer)
        out[header] = answer[start:end].strip()
    return out


def _leading_token(body: str) -> str:
    """First word-ish token of a section body — where an enum value lives
    (e.g. 'DEFERRED' in 'DEFERRED — insufficient signal…')."""
    stripped = body.lstrip("*-• \t")
    m = re.match(r"[A-Za-z_]+", stripped)
    return m.group(0) if m else ""
