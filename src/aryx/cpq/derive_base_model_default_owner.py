"""Derive the base model that owns a model's default configuration, when the Whitelist cannot narrow it to one.

Behind ``cpq_derive_base_model_default_owner_enabled``. A model such as APX N70 has several base models (one per
frequency band) whose Whitelist rows list every band, so the answer "country only" leaves all of them and the engine
asks the customer for details that belong to the base model (flashcode digits, band). The Defaultinattr table says
which of them is the model's default configuration: that base model defines defaults for every attribute its
siblings do, and more (the band among them). With 2+ base models left it is derived only when

* no attribute still separates the left base models (a frequency band or keypad each base model holds one value
  of): that attribute is asked, the default owner is never picked over it,
* every left base model has Defaultinattr rows (no data means no evidence),
* exactly one of them defines defaults for a strict superset of the attributes each of the others defines, and
* no value the customer gave (a typed answer or a wording match) differs from that base model's default for the
  same attribute: a customer who asked for another band is not given the default band's base model.

Never overrides the Whitelist narrowing (it runs only on what that narrowing leaves) and never guesses among 2+.
"""
from __future__ import annotations

from typing import Any

from aryx.config import get_settings
from aryx.cpq.base_model_defaults import base_model_own_defaults
from aryx.cpq.data_table.data_table_derive_base_model import (
    model_rows_and_base_models, narrowed_base_models, single_valued_discriminators,
)

# Source tags of values the customer gave (not the engine's picks).
CUSTOMER_SOURCES = ("user", "hint")
# The source tag of a base model derived this way: replaceable, re-checked every pass.
DEFAULT_OWNER_SOURCE = "derived_default_owner"


def default_owner_enabled() -> bool:
    return getattr(get_settings(), "cpq_derive_base_model_default_owner_enabled", False) is True


def default_owner_base_model(
    cpq_model: str, filled: dict[str, str], workspace_id: int, catalog_prefix: str,
    cache: dict[tuple, Any] | None, ignore_attrs: frozenset[str], customer_attrs: frozenset[str],
) -> str | None:
    """The base model owning the model's default configuration among those the known values leave, or None."""
    if not default_owner_enabled():
        return None
    rows, base_models = model_rows_and_base_models(cpq_model, workspace_id, catalog_prefix, cache)
    if len(base_models) < 2:
        return None
    remaining = narrowed_base_models(rows, filled, ignore_attrs)
    if len(remaining) < 2:
        return None
    if single_valued_discriminators(rows, remaining):
        return None                # an attribute still separates them: ask it, do not pick the default owner
    own = {bm: base_model_own_defaults(bm, workspace_id, catalog_prefix, cache) for bm in remaining}
    if any(not defaults for defaults in own.values()):
        return None
    owners = [bm for bm, defaults in own.items()
              if all(set(defaults) > set(other) for o, other in own.items() if o != bm)]
    if len(owners) != 1:
        return None
    owner = owners[0]
    for attr in customer_attrs:
        values = {v.strip().upper() for v in own[owner].get(attr, ())}
        if values and str(filled.get(attr, "")).strip().upper() not in values:
            return None
    return owner
