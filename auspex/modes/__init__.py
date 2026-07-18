"""Response modes (S9) — code-owned routing + typed output contracts for the
DEEP path. Format beats keywords (resolver); contracts compile to prompts +
validators (contract/catalog)."""

from auspex.modes.catalog import CONTRACTS, Mode, contract_for
from auspex.modes.contract import ContractField, ContractResult, ModeContract
from auspex.modes.resolver import resolve_mode

__all__ = [
    "CONTRACTS",
    "ContractField",
    "ContractResult",
    "Mode",
    "ModeContract",
    "contract_for",
    "resolve_mode",
]
