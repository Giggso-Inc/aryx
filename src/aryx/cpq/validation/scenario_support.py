"""Seed-state helpers for deterministic CPQ scenario generation."""
from __future__ import annotations

from typing import Any

from aryx.cpq.state import ConfigAttr
from aryx.cpq.validation.models import Scenario


def append_scenario(
    scenarios: list[Scenario], seen: set[tuple[object, ...]],
    scenario_id: str, filled: dict[str, str], limit: int,
    filled_multi: dict[str, tuple[str, ...]] | None = None,
) -> None:
    """Append one unique scalar/multi seed or fail at the configured bound."""
    multi = filled_multi or {}
    fingerprint: tuple[object, ...] = (
        tuple(sorted(filled.items())),
        tuple((key, multi[key]) for key in sorted(multi)),
    )
    if fingerprint in seen:
        return
    if len(scenarios) >= limit:
        raise ValueError(f"scenario limit {limit} exceeded")
    seen.add(fingerprint)
    sources = {key: "user" for key in (*filled, *multi)}
    scenarios.append(Scenario(
        scenario_id, dict(filled), sources, dict(multi),
    ))


def place_value(
    attr: ConfigAttr, value: str, filled: dict[str, str],
    filled_multi: dict[str, tuple[str, ...]],
) -> None:
    """Place an option in the state shape required by its select type."""
    if attr.select_type == "multi":
        filled_multi[attr.variable_name] = (value,)
        filled.pop(attr.variable_name, None)
    else:
        filled[attr.variable_name] = value
        filled_multi.pop(attr.variable_name, None)


def attribute_index(attrs: list[ConfigAttr]) -> dict[int, ConfigAttr]:
    """Index catalog attributes through both entity and source IDs."""
    index = {attr.entity_id: attr for attr in attrs}
    index.update({attr.source_id: attr for attr in attrs if attr.source_id is not None})
    return index


def first_non_match(attr: ConfigAttr, values: list[str]) -> str | None:
    """Return the first catalog option outside accepted condition values."""
    accepted = {value.strip().lower() for value in values}
    return next((
        option.item_value for option in sorted(attr.options, key=lambda item: item.order)
        if option.item_value.strip().lower() not in accepted
    ), None)


def split_values(encoded: str) -> list[str]:
    """Split the catalog's tilde-delimited OR encoding."""
    return [value.strip() for value in encoded.split("~") if value.strip()]


def rule_key(rule: Any) -> tuple[str, int, int, str]:
    """Return a stable rule-ordering key."""
    return (rule.rule_name, rule.target_attr_id, rule.condition_attr_id, rule.condition_value)
