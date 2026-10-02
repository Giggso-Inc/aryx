"""Exact-first Product matching (D11, aryxent PR 9), gated by
``cpq_product_match_exact_first_enabled``.

Two pieces, both inert with the flag off:

* ``resolved_model_seed_texts`` -- the Product option exactly equal to the
  turn's resolved model code, tried before the anchor text so the exact
  model wins.
* ``match_option_name`` -- the Product-option pass of
  ``resolve_product_hint``. Flag off it is the original first-hit
  bidirectional-substring scan. Flag on, an option whose normalized text
  EQUALS the hint wins first; otherwise among substring hits the one
  closest in length wins, so ``APX4000XH`` is not swallowed by the longer
  ``APX4000XHFLASHPORT``.
"""
from __future__ import annotations

from typing import Callable

from aryx.config import get_settings
from aryx.cpq import model_resolution as _model_resolution


def _enabled() -> bool:
    return bool(get_settings().cpq_product_match_exact_first_enabled)


def resolved_model_seed_texts(options: list | None = None) -> list[str]:
    """The item_value of the Product option exactly equal (case-insensitive)
    to the turn's resolved model's cpq code, as a one-element list, or []
    (flag off / no bound or unresolved turn / no exact option). Exact only,
    so the fuzzy apply_answer tiers never see a model code that is not a
    real option."""
    if not _enabled() or not options:
        return []
    ctx = _model_resolution.get_turn()
    if ctx is None or not ctx.resolution.resolved or ctx.resolution.chosen is None:
        return []
    code = ctx.resolution.chosen.cpq_model.upper()
    return [o.item_value for o in options if o.item_value.upper() == code][:1]


def match_option_name(
    options: list[tuple[str, str]], hint_norm: str, min_len: int,
    normalize: Callable[[str], str],
) -> str | None:
    """Display name (or item value) of the Product option matching
    `hint_norm`, or None. `options` are (item_value, display_name)."""
    exact_first = _enabled()
    loose: list[tuple[int, str]] = []
    for item_value, display_name in options:
        for text in (item_value, display_name):
            stripped = text.strip()
            is_code = any(c.isdigit() for c in stripped) or "/" in stripped
            if len(stripped.split()) < 2 and not is_code:
                continue  # same single-word guard as extract_catalog_hints
            norm = normalize(text)
            if min(len(norm), len(hint_norm)) < min_len:
                continue
            if exact_first and norm == hint_norm:
                return display_name or item_value
            if norm in hint_norm or hint_norm in norm:
                if not exact_first:
                    return display_name or item_value
                loose.append((len(norm), display_name or item_value))
                break
    if not loose:
        return None
    return min(loose, key=lambda pair: pair[0])[1]
