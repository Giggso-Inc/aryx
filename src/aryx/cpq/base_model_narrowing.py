"""Narrow a model's base models from the model's own answers, in both directions.

ws 1267, "I want a quote for APX 900": the model has 10 base models and each is fully determined by its frequency
band and keypad type (5 x 2). The customer cannot answer "which of 660 base model codes", so the engine asks for the
attributes that separate the base models and lets the existing derivation (`derive_base_model_from_known_attrs`) fill
the base model from the answers. Conversely a known base model fills those attributes.

Which attributes separate a model's base models is read from that model's own whitelist rows: an attribute does when
EVERY base model still in play has rows for it, each with exactly ONE value, and the values differ. "Still in play"
means the base models the known answers (the country, ...) have not already excluded, so an attribute whose value is
already decided is not asked. No attribute or model name appears here. Everything is flag-gated by the callers
(`cpq_base_model_narrowing_enabled`, and the derivation flag for the fill pass).
"""
from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass, field
from typing import Any

from aryx.cpq.data_table.data_table_derive_base_model import (
    model_rows_and_base_models, narrowed_base_models, row_attr_values,
)
from aryx.cpq.derive_base_model_pick import blind_attrs
from aryx.cpq.resolved_model_candidates import resolved_model_first_candidates


@dataclass(frozen=True)
class BaseModelNarrowing:
    """What the fill pass needs, computed once per pass.

    ask_first   -- visible, unanswered attributes that separate the base models still in play: asked, never guessed,
                   and the base model question waits for them.
    forward     -- {attribute: UPPER value} read off a base model the customer already has, for the separating
                   attributes that are still unanswered.
    base_model_codes -- the model's base model codes (UPPER), to tell a base model attribute from a part-number one.
    """

    ask_first: frozenset[str] = frozenset()
    forward: dict[str, str] = field(default_factory=dict)
    base_model_codes: frozenset[str] = frozenset()


def value_matches(allowed: Collection[str], item_value: str, display_name: str) -> bool:
    """True when an option's item value or display name is one of the UPPER-CASE `allowed` values.

    The one matching rule for the rows' values: the typed-phrase tie-break and the forward fill both use it, so a
    catalog whose whitelist holds display names behaves the same in both."""
    return item_value.strip().upper() in allowed or display_name.strip().upper() in allowed


def single_valued_discriminators(
    rows: list[dict[str, Any]], base_models: set[str],
) -> dict[str, dict[str, str]]:
    """{attribute: {base model: UPPER value}} for the attributes that separate `base_models`.

    Every base model has rows for the attribute, each base model holds exactly one value, and at least two different
    values exist. Attributes a base model lists several values for (a country list) or only some base models use are
    not separating, so they are left out."""
    per_attr: dict[str, dict[str, set[str]]] = {}
    for row in rows:
        base_model = str(row.get("BaseModel") or "").strip()
        if base_model not in base_models:
            continue
        for attr, value in row_attr_values(row):
            per_attr.setdefault(attr, {}).setdefault(base_model, set()).add(value)
    out: dict[str, dict[str, str]] = {}
    for attr, by_base_model in per_attr.items():
        if len(by_base_model) != len(base_models):
            continue
        if any(len(values) != 1 for values in by_base_model.values()):
            continue
        single = {bm: next(iter(values)) for bm, values in by_base_model.items()}
        if len(set(single.values())) >= 2:
            out[attr] = single
    return out


def _model_with_base_models(
    product: str, workspace_id: int, catalog_prefix: str, cache: dict | None,
) -> tuple[list[dict[str, Any]], set[str]]:
    """Rows and base models of the first candidate model that has two or more base models."""
    for cpq_model in resolved_model_first_candidates(product, workspace_id, catalog_prefix, cache):
        rows, base_models = model_rows_and_base_models(cpq_model, workspace_id, catalog_prefix, cache)
        if len(base_models) >= 2:
            return rows, base_models
    return [], set()


def discriminator_values(
    product: str, workspace_id: int | None, catalog_prefix: str, cache: dict | None = None,
) -> dict[str, frozenset[str]]:
    """{attribute: UPPER values} the product's model separates its base models by (for the hint tie-break)."""
    if workspace_id is None or not product:
        return {}
    rows, base_models = _model_with_base_models(product, workspace_id, catalog_prefix, cache)
    return {attr: frozenset(by_bm.values())
            for attr, by_bm in single_valued_discriminators(rows, base_models).items()}


def _flat(variable_name: str) -> str:
    return variable_name.lower().replace("_", "")


def build_base_model_narrowing(
    attrs: list[Any], filled: dict[str, str], sources: dict[str, str] | None, product: str,
    workspace_id: int | None, catalog_prefix: str, cache: dict | None = None,
) -> BaseModelNarrowing | None:
    """The narrowing for this pass, or None when there is nothing to narrow: no product, a model with fewer than two
    base models, no separating attribute, or the known answers already leave a single base model (the derivation
    fills it)."""
    if workspace_id is None or not product:
        return None
    rows, base_models = _model_with_base_models(product, workspace_id, catalog_prefix, cache)
    if len(base_models) < 2:
        return None
    from aryx.cpq.engine import _DECISION_REQUIRED_KEYS  # noqa: PLC0415 -- the engine imports this module's callers

    blind = blind_attrs(sources)
    by_vn = {a.variable_name: a for a in attrs}
    codes = {bm.upper(): bm for bm in base_models}

    def answered(vn: str) -> bool:
        return bool(filled.get(vn)) and vn not in blind

    def askable(vn: str) -> bool:
        """Visible, with options, not answered, and not a base model / part-number / country / region attribute (the
        last two have their own path)."""
        flat = _flat(vn)
        return (vn in by_vn and not by_vn[vn].hidden and bool(by_vn[vn].options) and not answered(vn)
                and "basemodel" not in flat and not any(key in flat for key in _DECISION_REQUIRED_KEYS))

    known = next((codes[str(filled[vn]).strip().upper()] for vn in by_vn
                  if "basemodel" in _flat(vn) and answered(vn) and str(filled[vn]).strip().upper() in codes), None)
    if known is not None:
        disc = single_valued_discriminators(rows, base_models)
        forward = {vn: disc[vn][known] for vn in disc if askable(vn)}
        return BaseModelNarrowing(forward=forward, base_model_codes=frozenset(codes)) if forward else None
    remaining = narrowed_base_models(rows, filled, blind)          # what the known answers have not excluded yet
    if len(remaining) < 2:
        return None
    ask_first = frozenset(vn for vn in single_valued_discriminators(rows, remaining) if askable(vn))
    return BaseModelNarrowing(ask_first=ask_first, base_model_codes=frozenset(codes)) if ask_first else None


def reopen_guessed_values(
    narrowing: BaseModelNarrowing | None, filled: dict[str, str], display_filled: dict[str, str],
    sources: dict[str, str] | None,
) -> list[str]:
    """Forget a GUESSED value of an attribute the narrowing asks or forward-fills, so it is asked / filled instead.

    A guess made earlier (an earlier turn, or an earlier pass before the product was known) is kept by the "already
    filled" stage, so the attribute would never be asked while the base model waits for it. Only guesses are
    reopened, never an answer. Returns the attributes reopened."""
    if narrowing is None or not sources:
        return []
    blind = blind_attrs(sources)
    reopened = [vn for vn in (*narrowing.ask_first, *narrowing.forward) if vn in blind and vn in filled]
    for vn in reopened:
        filled.pop(vn, None)
        display_filled.pop(vn, None)
        sources.pop(vn, None)
    return reopened
