"""Typed output contracts for the DEEP path — S9 (ADR 0007 spirit: specs over
prompts). A contract is the single source of truth for a mode's output shape; it
COMPILES to (a) the system-prompt directive that instructs the model, and (b)
the validator that checks the model actually produced it. We never hand-write
the prompt and validator separately and hope they agree — the spec generates
both, so they stay in lockstep on the spec's fields.

Contracts describe named sections of the analyst answer (plain text, `## Name`
headers — the chat UI renders verbatim). A field may be an enum (a closed set of
allowed values, e.g. a risk level); the validator checks membership in code
(post-hoc, never by trusting the model — ADR 0006 spirit) and REPORTS
non-conformance. It observes correctness; it does not block a streamed answer
(the repair loop is TD-012).
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
    """A mode's typed output contract. `purpose` + `fields` + `rules` compile to
    the system directive; `fields` alone compile to the validator (`rules` are
    prompt-only guidance — surfaced to the model, never machine-checked)."""

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

    def validate(self, answer: str, pinned: dict[str, str] | None = None) -> ContractResult:
        """Validate a produced answer against the contract (specs → validators).
        Structural + enum checks only — never a semantic judgement of quality.

        `pinned` maps a field name to the value a code-owned verdict already
        decided for THIS answer (e.g. alert_triage's Risk from the additive
        scorer): the rendered leading token must EQUAL it, not merely sit in the
        enum. Membership alone would let a steered model swap one valid level
        for another undetected — the "use it exactly" prompt instruction is not
        an enforcement mechanism (ADR 0006), this check is."""
        present = _sections(answer)
        missing: list[str] = []
        bad_enum: list[str] = []
        pin_broken: list[str] = []
        for f in self.fields:
            body = present.get(f.name.lower())
            # Absent OR present-but-empty (header emitted, no content) both fail a
            # required section — a headers-only skeleton is not a conformant answer.
            if not body:
                if f.required:
                    missing.append(f.name)
                continue
            token = _leading_token(body)
            if f.allowed_values:
                allowed = {v.lower() for v in f.allowed_values}
                if token.lower() not in allowed:
                    bad_enum.append(f"{f.name}={token or '∅'}")
            expected = (pinned or {}).get(f.name)
            if expected is not None and token.lower() != expected.lower():
                pin_broken.append(f"{f.name}={token or '∅'}≠{expected}")
        return ContractResult(
            mode=self.name,
            missing=tuple(missing),
            bad_enum=tuple(bad_enum),
            pinned_mismatch=tuple(pin_broken),
        )


@dataclass(frozen=True)
class ContractResult:
    mode: str
    missing: tuple[str, ...] = ()  # required sections absent
    bad_enum: tuple[str, ...] = ()  # enum fields with an out-of-set value
    pinned_mismatch: tuple[str, ...] = ()  # fields that diverged from a code verdict

    @property
    def ok(self) -> bool:
        return not self.missing and not self.bad_enum and not self.pinned_mismatch

    def reason(self) -> str:
        parts = []
        if self.missing:
            parts.append(f"missing sections: {', '.join(self.missing)}")
        if self.bad_enum:
            parts.append(f"out-of-contract values: {', '.join(self.bad_enum)}")
        if self.pinned_mismatch:
            parts.append(f"code-verdict mismatch: {', '.join(self.pinned_mismatch)}")
        return "; ".join(parts) or "ok"


# A section header is a `## Name` ATX heading. We require ≥2 hashes: contracts
# always compile to `##`, and a single `#` is how models write shell/YAML
# comments inside code samples — matching those forged phantom sections.
_SECTION_RE = re.compile(r"^#{2,6}[ \t]*(.+?)[ \t]*$", re.MULTILINE)
# Field names never contain a colon or a dash, so the first such separator on a
# header line delimits the name from an inline value ("Risk: HIGH", "Risk — HIGH").
_HEADER_SPLIT_RE = re.compile(r"\s*[:—–]\s*|\s-\s")
_EMPHASIS = "*_`~ "
_TOKEN_RE = re.compile(r"[A-Za-z]+")


def _split_header(raw: str) -> tuple[str, str]:
    """Split a header line into (name, inline-value). Models sometimes place the
    value on the header itself ('Risk: HIGH'); the value then leads the body."""
    parts = _HEADER_SPLIT_RE.split(raw, maxsplit=1)
    return (parts[0], parts[1]) if len(parts) == 2 else (raw, "")


def _sections(answer: str) -> dict[str, str]:
    """Split an answer into {header-lowercased: body}. A header is a `##…######`
    ATX heading; matching is case-insensitive and tolerant of markdown emphasis
    ('**Risk**') and of an inline enum value on the header line ('Risk: HIGH',
    'Risk — HIGH') — the compiled directive renders `## Name — description`, so
    the validator must accept the header shapes the spec teaches. First header
    wins on duplicates (a later `## Risk` can't silently override the first)."""
    out: dict[str, str] = {}
    matches = list(_SECTION_RE.finditer(answer))
    for i, m in enumerate(matches):
        name_part, inline = _split_header(m.group(1).strip())
        header = name_part.strip(_EMPHASIS).lower()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(answer)
        body = answer[start:end].strip()
        if inline:
            body = f"{inline}\n{body}".strip()
        out.setdefault(header, body)
    return out


def _leading_token(body: str) -> str:
    """First word-ish token of a section body — where an enum value lives
    (e.g. 'DEFERRED' in 'DEFERRED — insufficient signal…'). A clean enum value
    stands alone: if the token is immediately followed by '/' or '-' it is a
    compound/hedge ('LOW/MEDIUM', 'LOW-MEDIUM') — return the whole chunk so it
    fails the enum rather than passing on its first component (S9 review)."""
    stripped = body.lstrip("*-•_` \t")
    m = _TOKEN_RE.match(stripped)
    if not m:
        return ""
    if stripped[m.end() : m.end() + 1] in "/-":
        return stripped.split(None, 1)[0]
    return m.group(0)
