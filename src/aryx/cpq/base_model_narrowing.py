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
    model_rows_and_base_models, narrowed_base_models, row_attr_values, single_valued_discriminators,
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
    order       -- {attribute: Seq} the model's own AttrSequence rows give the `ask_first` attributes: the order the
                   real screen shows them in (empty when the rows have none).
    """

    ask_first: frozenset[str] = frozenset()
    forward: dict[str, str] = field(default_factory=dict)
    base_model_codes: frozenset[str] = frozenset()
    order: dict[str, int] = field(default_factory=dict)


def value_matches(allowed: Collection[str], item_value: str, display_name: str) -> bool:
    """True when an option's item value or display name is one of the UPPER-CASE `allowed` values.

    The one matching rule for the rows' values: the typed-phrase tie-break and the forward fill both use it, so a
    catalog whose whitelist holds display names behaves the same in both."""
    return item_value.strip().upper() in allowed or display_name.strip().upper() in allowed


def _named_model_with_base_models(
    product: str, workspace_id: int, catalog_prefix: str, cache: dict | None,
) -> tuple[str, list[dict[str, Any]], set[str]]:
    """Name, rows and base models of the first candidate model that has two or more base models."""
    for cpq_model in resolved_model_first_candidates(product, workspace_id, catalog_prefix, cache):
        rows, base_models = model_rows_and_base_models(cpq_model, workspace_id, catalog_prefix, cache)
        if len(base_models) >= 2:
            return cpq_model, rows, base_models
    return "", [], set()


def _model_with_base_models(
    product: str, workspace_id: int, catalog_prefix: str, cache: dict | None,
) -> tuple[list[dict[str, Any]], set[str]]:
    """Rows and base models of the first candidate model that has two or more base models."""
    _model, rows, base_models = _named_model_with_base_models(product, workspace_id, catalog_prefix, cache)
    return rows, base_models


_SEQ_ORDER_MEMO: dict[tuple, tuple[list, dict[str, int]]] = {}
_SEQ_ORDER_MEMO_MAX = 256


def attr_sequence_order(
    cpq_model: str, base_models: Collection[str], attr_names: Collection[str],
    workspace_id: int, catalog_prefix: str, cache: dict | None = None,
) -> dict[str, int]:
    """{attribute: lowest Seq} of `attr_names` in the model's AttrSequence rows for `base_models`.

    The sequence is the order the real screen asks the attributes in (ws 1267, APX 900: Frequency Bands 33, Keypad
    Type 39, for every base model). A non-numeric Seq is skipped; an attribute with no usable Seq is left out."""
    from aryx.cpq.data_table.data_table_loader import _load_all_tables  # noqa: PLC0415 -- data layer, flag-gated callers

    wanted, bms, model = set(attr_names), set(base_models), (cpq_model or "").strip().upper()
    out: dict[str, int] = {}
    try:
        sequence_rows = _load_all_tables(workspace_id, catalog_prefix, cache)[1]
    except Exception:  # noqa: BLE001 -- the order is a nicety, never a reason to lose the narrowing
        return {}
    # The row scan is the cost: reuse it while the loaded table is the same object (the loader caches it).
    memo_key = (id(sequence_rows), len(sequence_rows), model, frozenset(bms), frozenset(wanted))
    hit = _SEQ_ORDER_MEMO.get(memo_key)
    if hit is not None and hit[0] is sequence_rows:      # the memo holds the list, so its id cannot be reused
        return dict(hit[1])
    for row in sequence_rows:
        name = str(row.get("AttrName") or "")
        if (name not in wanted or str(row.get("CPQModel") or "").strip().upper() != model
                or str(row.get("BaseModel") or "").strip() not in bms):
            continue
        try:
            seq = int(float(row.get("Seq")))
        except (TypeError, ValueError):
            continue
        out[name] = min(seq, out.get(name, seq))
    if len(_SEQ_ORDER_MEMO) >= _SEQ_ORDER_MEMO_MAX:
        _SEQ_ORDER_MEMO.clear()
    _SEQ_ORDER_MEMO[memo_key] = (sequence_rows, dict(out))
    return out


def discriminator_values(
    product: str, workspace_id: int | None, catalog_prefix: str, cache: dict | None = None, cpq_model: str = "",
) -> dict[str, frozenset[str]]:
    """{attribute: UPPER values} the product's model separates its base models by (for the hint tie-break).

    `cpq_model`, when the caller already knows the model (resolved from the customer's wording), is used directly;
    otherwise the model is looked up from `product`."""
    if workspace_id is None or not (product or cpq_model):
        return {}
    if cpq_model:
        rows, base_models = model_rows_and_base_models(cpq_model, workspace_id, catalog_prefix, cache)
        if len(base_models) < 2:
            rows, base_models = _model_with_base_models(product, workspace_id, catalog_prefix, cache) if product else ([], set())
    else:
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
    cpq_model, rows, base_models = _named_model_with_base_models(product, workspace_id, catalog_prefix, cache)
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
    if not ask_first:
        return None
    return BaseModelNarrowing(
        ask_first=ask_first, base_model_codes=frozenset(codes),
        order=attr_sequence_order(cpq_model, remaining, ask_first, workspace_id, catalog_prefix, cache))


def order_ask_first(pending: list[Any], narrowing: BaseModelNarrowing | None) -> list[Any]:
    """`pending` with the narrowing's own questions asked in the model's AttrSequence order.

    Only the positions those questions already hold are reshuffled, among themselves, so nothing else moves and
    an attribute without a Seq keeps its place. No narrowing / no order: the list as it was."""
    if narrowing is None or not narrowing.order:
        return pending
    slots = [i for i, attr in enumerate(pending) if attr.variable_name in narrowing.order]
    if len(slots) < 2:
        return pending
    ordered = sorted((pending[i] for i in slots), key=lambda attr: narrowing.order[attr.variable_name])
    out = list(pending)
    for i, attr in zip(slots, ordered):
        out[i] = attr
    return out


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


def discriminator_option_limits(
    attrs: list[Any], filled: dict[str, str], sources: dict[str, str] | None, product: str,
    workspace_id: int | None, catalog_prefix: str, cache: dict | None = None,
) -> dict[str, list[str]]:
    """{entity_id: item values} the customer may still choose for each separating attribute.

    The values are the ones the base models still in play hold for that attribute, so the list shows the model's
    own bands / keypads and not every option the catalog defines for the attribute. An attribute whose rows leave
    none of its options out, or match no option at all, is left out (its full list stays)."""
    narrowing = build_base_model_narrowing(attrs, filled, sources, product, workspace_id, catalog_prefix, cache)
    if narrowing is None or not narrowing.ask_first:
        return {}
    rows, base_models = _model_with_base_models(product, workspace_id, catalog_prefix, cache)
    remaining = narrowed_base_models(rows, filled, blind_attrs(sources))
    disc = single_valued_discriminators(rows, remaining)
    by_vn = {a.variable_name: a for a in attrs}
    limits: dict[str, list[str]] = {}
    for vn in narrowing.ask_first:
        attr = by_vn[vn]
        allowed = set(disc[vn].values())
        kept = [o.item_value for o in attr.options if value_matches(allowed, o.item_value, o.display_name)]
        if kept and len(kept) < len(attr.options):
            limits[attr.entity_id] = kept
    return limits
