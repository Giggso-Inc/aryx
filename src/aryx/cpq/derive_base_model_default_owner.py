"""Derive the base model that owns a model's default configuration, when the Whitelist cannot narrow it to one.

Behind ``cpq_derive_base_model_default_owner_enabled``. A model such as APX N70 has several base models (one per
frequency band) whose Whitelist rows list every band, so the answer "country only" leaves all of them and the engine
asks the customer for details that belong to the base model (flashcode digits, band). The Defaultinattr table says
which of them is the model's default configuration: that base model defines defaults for every attribute its
siblings do, and more (the band among them). With 2+ base models left it is derived only when

* when no attribute separates the left base models (N70: every base model lists every band): every left base model
  has Defaultinattr rows (no data means no evidence) and exactly one of them defines defaults for a strict superset
  of the attributes each of the others defines,
* when an attribute still separates them (a frequency band or keypad each base model holds one value of, N30 / N50):
  that attribute is asked unless the catalog names a default for it. Every separating attribute the customer has not
  answered must have a Defaultinattr default that exactly one left base model holds as its own value (N50: the band
  default 700/800 MHz is defined for one of the three base models only), and it must be the same base model for all
  of them. An attribute with no such default (APX 900: no band default in any base model) is asked, and
* in both cases no value the customer gave (a typed answer or a wording match) differs from that base model's
  default for the same attribute: a customer who asked for another band is not given the default band's base model.

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
    own = {bm: base_model_own_defaults(bm, workspace_id, catalog_prefix, cache) for bm in remaining}
    separating = single_valued_discriminators(rows, remaining)
    unanswered = {attr: held for attr, held in separating.items()
                  if attr in ignore_attrs or not str(filled.get(attr, "")).strip()}
    if separating and not unanswered:
        return None                # the separating attributes are all answered yet 2+ remain: nothing to derive from
    owner = _owner_by_separating_defaults(unanswered, own) if unanswered else _owner_by_most_defaults(own)
    if owner is None:
        return None
    for attr in customer_attrs:
        values = {v.strip().upper() for v in own[owner].get(attr, ())}
        if values and str(filled.get(attr, "")).strip().upper() not in values:
            return None
    return owner


def _owner_by_most_defaults(own: dict[str, dict[str, set[str]]]) -> str | None:
    """No attribute separates the base models: the one whose Defaultinattr attributes strictly contain every other's."""
    if any(not defaults for defaults in own.values()):
        return None
    owners = [bm for bm, defaults in own.items()
              if all(set(defaults) > set(other) for o, other in own.items() if o != bm)]
    return owners[0] if len(owners) == 1 else None


def _owner_by_separating_defaults(
    unanswered: dict[str, dict[str, str]], own: dict[str, dict[str, set[str]]],
) -> str | None:
    """Every unanswered separating attribute has a default that exactly one base model holds as its own value, and it
    is the same base model for all of them; None when any of them has no such default (that attribute is asked)."""
    chosen: set[str] = set()
    for attr, held in unanswered.items():
        owners = {bm for bm, value in held.items()
                  if {v.strip().upper() for v in own.get(bm, {}).get(attr, ())} == {value}}
        if len(owners) != 1:
            return None
        chosen |= owners
    return next(iter(chosen)) if len(chosen) == 1 else None
