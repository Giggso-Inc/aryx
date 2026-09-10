"""Menu-option display-value lookup shared by `build_payload`'s scalar,
multi-select, and array-set serialization stages (Phase 4, docs/RAVEN_
STYLE_COMPLIANCE_PLAN_2026-09-03.md). Logic unchanged from the original
`_display_for` closure.
"""

from __future__ import annotations

from typing import Any


def display_for(attr: Any, value: str) -> str:
    return next(
        (o.display_name for o in attr.options if o.item_value == value),
        value,
    )
