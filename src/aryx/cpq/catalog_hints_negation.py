"""Negation-suppression pass for ``catalog_hints.extract_catalog_hints``
(Phase 4, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). Split off
purely to keep both files under the file-size cap -- logic unchanged.

Module-level helpers are read off the engine MODULE object (never
patched by any test, but kept consistent with the sibling file's own
`_engine_module.<name>` convention).
"""

from __future__ import annotations

from typing import Any

from aryx.cpq import engine as _engine_module


def find_negated_vns(
    engine: Any,
    attrs: list["Any"],
    all_owners: dict[str, set[str]],
    candidates: dict[str, list[tuple[str, str]]],
    hints: dict[str, str],
    q_norm: str,
    q_lower: str,
    q_index_map: list[int],
) -> set[str]:
    """variable_names whose concept appeared in the question immediately
    after a negation cue ("exclude", "no", "without", ...) rather than
    as a positive selection. Callers must not silently auto-fill these
    via blind first-by-order — confirmed live: "exclude any multikey
    capability" produced zero positive hint for multikeyType_astro (its
    real option text is a single dictionary word, never trusted as a
    positive `candidates` entry), so it fell through to auto_fill's
    ungoverned fallback and landed on the literal opposite, "MULTIKEY",
    even though a "No Multikey" option exists.

    Mutates `hints` in place too: when a negated phrase's real catalog
    also spells out the negation as its own option — "no{phrase}" (or
    its plural-flip) found as a key in `candidates`, same-attr or a
    sibling — that option is asserted into `hints` directly, since
    passive suppression alone doesn't stop an attr's own unconditional
    default_value from applying (confirmed live: beltClipType_astro
    kept its "2.0 INCH / 5.08 CM (STANDARD)" default after "exclude
    any... carry solutions" even though "NO CARRY SOLUTION" is a real
    option on that very attr, and multikeyType_astro was simply left
    unfilled after "exclude any multikey capability" even though both
    attrs have their own literal "NO <X>" option in the real catalog).
    Same len(owners)==1 never-guess guard as the rest of this method.
    """
    # docs/CPQ_REGEX_VS_LLM_ANCHOR_GUARDRAIL_AUDIT_2026_08_12.md row
    # 17: a deterministic sanity check, not an LLM call — negating an
    # attr's ONLY real (non-boolean) option is contradictory (there's
    # nothing left to fall back to), so it must never silently
    # suppress the whole attribute the way a genuine "exclude X, use
    # Y instead" negation among 2+ real options correctly does.
    # Cheap: reuses `attrs` already scoped to this call, no new rule
    # evaluation or threading needed.
    _attr_by_vn = {a.variable_name: a for a in attrs}

    def _has_only_one_real_option(vn: str) -> bool:
        attr = _attr_by_vn.get(vn)
        if attr is None:
            return False
        real_opts = [
            o for o in attr.options
            if o.item_value.strip().lower() not in engine._BOOLEAN_DISPLAY_VALUES
        ]
        return len(real_opts) <= 1

    negated_vns: set[str] = set()
    for phrase, owners in all_owners.items():
        idx = _engine_module._find_plural_tolerant(q_norm, phrase)
        if idx == -1:
            continue
        if not _engine_module._is_negated_before(q_lower, q_index_map[idx]):
            continue
        negated_vns.update(vn for vn in owners if not _has_only_one_real_option(vn))
        # When the option text spells the negation out explicitly — on
        # the SAME attr (multikeyType_astro: "MULTIKEY" negated -> "NO
        # MULTIKEY" also on multikeyType_astro) or a SIBLING one in this
        # catalog (accessoriesSolutionSet_astro's "CARRY SOLUTIONS"
        # negated -> beltClipType_astro's "NO CARRY SOLUTION") — assert
        # that option directly instead of leaving the field to a
        # default or an unfilled gap. Reuses `candidates` (already
        # built by the caller from this same catalog-scoped `attrs`,
        # multi-word/code trust filter already applied) — no extra scan
        # of the catalog, and the same len(owners)==1 guard as every
        # other match in this method: never guess which attr "NO X"
        # belongs to if more than one real option has it.
        no_key = f"no{phrase}"
        no_key_variant = f"no{phrase[:-1]}" if phrase.endswith("s") else f"no{phrase}s"
        for key in (no_key, no_key_variant):
            no_entries = candidates.get(key)
            if not no_entries:
                continue
            no_owners = {vn for vn, _iv in no_entries}
            if len(no_owners) != 1:
                continue  # real "NO X" option on 2+ attrs — never guess
            target_vn, target_value = no_entries[0]
            if target_vn not in hints:
                hints[target_vn] = target_value
            break
    return negated_vns
