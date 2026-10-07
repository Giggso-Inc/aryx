"""``extract_catalog_hints`` (Phase 4, one of the 8 previously-deferred
oversized `CpqEngine` methods, docs/RAVEN_STYLE_COMPLIANCE_PLAN_
2026-09-03.md). The negation-suppression pass (the second half of the
original method) lives in `catalog_hints_negation.py`. Module-level
helpers are read off the engine MODULE object.
"""

from __future__ import annotations

from typing import Any

from aryx.cpq import engine as _engine_module
from aryx.cpq.catalog_hints_negation import find_negated_vns
from aryx.cpq.catalog_hints_product import product_selector_entries
from aryx.cpq.catalog_hints_tie import single_entry


def extract_catalog_hints(
    engine: Any, question: str, attrs: list["Any"],
    discriminators: dict[str, frozenset[str]] | None = None,
) -> tuple[dict[str, str], set[str]]:
    """Extract hints by matching real menu-option text against the question.

    Complements extract_hints()'s fixed pattern list (hwversion/country
    concepts only now — product detection moved to the dynamic
    _ingested_product_names lookup) — confirmed live, a fixed list
    silently drops anything outside the concepts it names. Rather than
    adding a hardcoded pattern per concept, scans every visible, single/
    boolean attr's real options and checks whether that option's own
    text (item_value or display_name) appears verbatim in the question,
    punctuation/casing stripped. Returns (hints, negated_vns):
      - hints — {variable_name: item_value}, keyed by the exact
        variable_name (unlike extract_hints()'s fragment keys) since the
        match already identifies the attribute, no fuzzy lookup needed.
      - negated_vns — variable_names whose concept appeared after a
        negation cue ("exclude", "no", "without", ...) rather than as a
        positive selection (see `catalog_hints_negation.find_negated_
        vns`'s docstring for the full contract, incl. the "NO X"
        catalog-option assertion also folded into `hints`).

    Never guesses (D2), several ways:
      - Same option text real for 2+ different attrs -> neither is
        hinted, EXCEPT the one narrow case `product_selector_entries`
        carves out: when one of the owning attrs is the platform's
        product selector (catalog_profile.PRODUCT_LITERAL), that one
        wins and the others stay unhinted -- a quote request names the
        product being quoted, so the ambiguity is resolved in its favor
        specifically (ws 1267, 2026-10-07: "APX 900" is also an option
        of the DMS picker productSelectionDMSO_astro). Every other
        multi-owner case is still never-guess. A broader tie-break via a
        distinguishing word from the attr's own variable_name was tried
        and REJECTED after two confirmed false positives: "software" in
        "baseline release software" self-referentially anchored
        softwareBundlesBundleType_astro (the word only overlapped
        because it's also in that attr's own name), and "SIM" anchored
        selectSecondarySIMCard_astro over the intended
        sIMCardSelection_astro (an artifact of the latter's leading
        lowercase "s" splitting under camelCase parsing).
      - A candidate phrase must be multi-word OR contain a digit/slash
        to be trusted as a positive hint, even with a single owner — a
        lone dictionary word is too easily coincidental (e.g. "SOFTWARE"
        is a real, sole-owner option for relatedServicesType_astro, but
        means nothing inside "baseline release software"). Multi-word
        phrases and punctuation-joined codes like "ATT/FIRSTNET"
        (confirmed live: excluding it as a "single word" dropped the
        hint for wirelessCarrier_astro despite "AT&T/FirstNet" verbatim
        in the message) aren't at that same accidental-match risk.
      - A positive-looking match is discarded if a negation cue sits in
        the ~40 chars right before it in the real question text —
        "exclude ... carry solutions" must not select "Carry Solutions"
        just because that literal phrase appears in the sentence.

    Longer/more specific option text is tried first (a short phrase must
    not shadow a longer, more specific one also present). Options coded
    by a generic boolean item_value (YES/NO) are excluded even with an
    elaborate display_name (e.g. item_value="YES", display_name=
    "Baseline Release") — matching those via display text alone is
    exactly the ambiguous-duplicate case D2
    exists to avoid; the real, specifically-named option should win.
    """
    q_norm, q_index_map = _engine_module._normalize_for_hint_with_map(question)
    q_lower = question.lower()
    candidates: dict[str, list[tuple[str, str]]] = {}
    displays: dict[tuple[str, str], str] = {}      # (attribute, item value) -> display name, for the model tie-break
    # Every real option's normalized text and its owning attr(s) — used
    # for negation-suppression below regardless of word count or
    # ambiguity (suppressing a blind fallback is low-risk: worst case is
    # an extra question asked, not a wrong value silently picked, so
    # it's fine to be broader here than the positive-hint match below).
    all_owners: dict[str, set[str]] = {}
    for attr in attrs:
        if attr.hidden:
            continue
        for opt in attr.options:
            if opt.item_value.strip().lower() in engine._BOOLEAN_DISPLAY_VALUES:
                continue
            _texts = [(opt.item_value, False), (opt.display_name, False)]
            _suffix = _engine_module._parenthetical_suffix(opt.display_name)
            if _suffix and _suffix not in (opt.item_value, opt.display_name):
                _texts.append((_suffix, True))
            for text, _is_suffix in _texts:
                stripped = text.strip()
                is_code = any(c.isdigit() for c in stripped) or "/" in stripped
                norm = _engine_module._normalize_for_hint(text)
                if len(norm) < _engine_module._HINT_MIN_PHRASE_LEN:
                    continue
                # Multi-select attrs still register here (needed so a
                # negated category on a multi-select attr, e.g.
                # accessoriesSolutionSet_astro's "CARRY SOLUTIONS", can be
                # detected as negated below and used to look up a
                # sibling's "NO <X>" option) but are excluded from
                # `candidates` just below — never a positive-hint target,
                # unchanged from before.
                all_owners.setdefault(norm, set()).add(attr.variable_name)
                if attr.select_type == "multi":
                    continue
                if len(stripped.split()) < 2 and not is_code:
                    # Single-word dictionary-style options are never
                    # trusted as a positive hint (see docstring) — still
                    # recorded above for negation-suppression, just not
                    # added to `candidates` below.
                    continue
                if _is_suffix and not is_code:
                    # A parenthetical suffix is shorter/more generic-
                    # sounding than the full option text it's plucked
                    # from ("Best Value") — multi-word alone isn't
                    # enough distinctiveness (raven review); only trust
                    # it when it also looks like a code (digit/slash) —
                    # "4G LTE+5G" qualifies, marketing prose does not.
                    continue
                candidates.setdefault(norm, []).append(
                    (attr.variable_name, opt.item_value))
                displays[(attr.variable_name, opt.item_value)] = opt.display_name

    hints: dict[str, str] = {}
    for phrase in sorted(candidates, key=len, reverse=True):
        idx = _engine_module._find_plural_tolerant(q_norm, phrase)
        if idx == -1:
            continue
        # 2+ owning attrs: never guess, unless one is the product selector
        # (see product_selector_entries); [] means skip this phrase.
        entries = product_selector_entries(candidates[phrase], discriminators, displays)
        if not entries:
            continue
        # Same attr, but 2+ genuinely different real values can share this
        # phrase (e.g. a "(4G LTE+5G)" variant suffix shared by sibling
        # products "APX NEXT"/"APX NEXT XE"). Never guess between them --
        # except on the product selector, where exactly one value's own code
        # being the phrase prefers that value (see catalog_hints_tie).
        selected = single_entry(entries, phrase, q_norm)
        if selected is None:
            continue
        vn, item_value = selected
        if vn in hints:
            continue  # a longer, more specific phrase already matched this attr
        if _engine_module._is_negated_before(q_lower, q_index_map[idx]):
            continue  # "exclude ... <phrase>" — not a selection
        hints[vn] = item_value

    negated_vns = find_negated_vns(
        engine, attrs, all_owners, candidates, hints, q_norm, q_lower, q_index_map,
    )
    return hints, negated_vns
