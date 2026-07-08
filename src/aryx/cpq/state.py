"""CPQ session state — serialisable so the UI can echo it back each turn."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class MenuOption:
    """One selectable value for a configuration attribute."""

    item_value: str    # API backend code sent to CPQ BOM API (e.g. "US")
    display_name: str  # Friendly label shown to the sales rep (e.g. "United States")
    order: int = 999


@dataclass
class ConfigAttr:
    """One configuration attribute extracted from the knowledge graph."""

    entity_id: int
    variable_name: str   # CPQ backend key (e.g. "hWVersion_astro")
    display_label: str   # Human label shown in conversation
    required: bool
    default_value: str
    options: list[MenuOption]  # empty → free-text input
    order: int = 999
    tier: str = "independent"  # "independent" | "dependent"


@dataclass
class CpqSession:
    """Accumulated state across all conversation turns.

    Serialised as JSON in the API response so the client can echo it back
    on the next turn — no server-side session store required.
    """

    mode: str = "cpq"
    product_name: str = ""
    product_entity_id: int = 0
    # variable_name → item_value (API code stored, never display label)
    filled: dict[str, str] = field(default_factory=dict)
    # variable_name → friendly display label (shown to user in summary)
    display_filled: dict[str, str] = field(default_factory=dict)
    # variable_names not yet answered
    pending_variables: list[str] = field(default_factory=list)
    turn: int = 0
    complete: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "CpqSession":
        known = {k for k in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})
