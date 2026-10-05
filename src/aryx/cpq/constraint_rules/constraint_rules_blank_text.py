"""Condition-script variables with BML's empty-string reading of unset text.

In BML an unset text variable is "". The engine's `filled` only holds what was
answered, so a condition script that tests such a variable stays unknown. With
flag `cpq_blank_free_text_in_conditions_enabled`, every free-text attribute (no
menu options, single value) that has no value is added as "" for condition-script
evaluation only. Menu attributes stay unknown until chosen. No names are listed.
"""
from __future__ import annotations

from typing import Any

from aryx.config import get_settings


def with_blank_free_text(attrs: list[Any], filled: dict[str, str]) -> dict[str, str]:
    """`filled` plus "" for each unfilled free-text attribute; `filled` itself when the flag is off."""
    if not get_settings().cpq_blank_free_text_in_conditions_enabled:
        return filled
    out = dict(filled)
    for attr in attrs:
        name = getattr(attr, "variable_name", "")
        if name and not out.get(name) and not attr.options and attr.select_type == "single":
            out[name] = ""
    return out
