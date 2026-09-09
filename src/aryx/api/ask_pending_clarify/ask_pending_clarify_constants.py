"""Shared stopword/tokenizer constants and the catalog-wide-naming-part
helper for the pending-clarify grounding scorer, split out of `api/
ask_api.py` (Phase 2/11-phase ask_api decomposition, docs/RAVEN_STYLE_
COMPLIANCE_PLAN_2026-09-03.md). Logic unchanged from the original inline
definitions.
"""

from __future__ import annotations

import re

_CLARIFY_STOPWORDS = frozenset({
    "change", "set", "update", "make", "switch", "modify", "edit", "alter",
    "please", "the", "a", "an", "to", "for", "my", "our", "me", "i", "want",
    "would", "like", "can", "you", "it", "this", "that", "and", "or", "of",
    "in", "on", "with", "from", "into", "value", "field", "attribute", "attr",
    "which", "what", "one", "option", "options",
    # Copula/auxiliary verbs — as generic as "and"/"or"/"of" above, just
    # missed. Live-confirmed: "what IS the carrier being selected" let
    # "is" survive the filter and false-match every already-filled
    # attribute whose display_label happens to start with "Is " (a common
    # BM-catalog boolean-flag naming convention: "Is provisioning
    # required...", "Is Quantity of X > 0", etc.) — none of them related
    # to carrier/product at all.
    "is", "are", "was", "were", "be", "being", "been",
    # docs/config_consistency_issues_2026-07-30.md — "change the product to
    # APX NEXT XE All Band" produced a bogus 8-attribute disambiguation
    # (Accessories Help Text, ConfigProcessStep, MSI Releases, modelname,
    # a HIDDEN internal rule attr, ...) — every one of them matched purely
    # because "All" (from the product's own name, "...XE All Band")
    # survived tokenization and word-overlapped the extremely common BM
    # catalog variable-name suffix "_all" (msiReleases_All, modelname_all,
    # accessoriesHelpText_all, ...), and each was already filled with
    # internal/HTML boilerplate, satisfying the is_filled branch. As
    # generic and collision-prone as "one"/"option" above once a catalog
    # uses "_all" as a naming convention — never itself a meaningful
    # signal for which attribute a customer means.
    "all",
})
_WORD_TOKEN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)


def _catalog_wide_naming_parts(attrs: list) -> set:
    """Generic (no catalog/suffix name hardcoded) replacement for hand-
    maintaining one stopword per catalog family: `_CLARIFY_STOPWORDS`
    already carries "all" specifically because "_all" is a near-
    universal BM-catalog variable_name suffix (msiReleases_All,
    modelname_all, accessoriesHelpText_all, ...) that single-handedly
    word-overlaps every such attribute whenever it survives tokenization
    (docs/config_consistency_issues_2026-07-30.md). Live-confirmed
    2026-08-21: the identical shape recurs with "_viSoln" on the video-
    solutions catalog family (present on virtually every attribute --
    archeType_viSoln, smartDockConfigServiceNoVideoStorage_viSoln,
    includeASpareBatteryWithEachBodyCamera_viSoln, ...) -- a customer
    echoing back a suggested variable_name (e.g. "mountingTypeArray_
    viSoln") floods the candidate list with every other "_viSoln"
    attribute via that one meaningless shared fragment. Rather than add
    "visoln" as the next hardcoded entry (repeating this same live
    incident for the NEXT catalog's own suffix), derive it from `attrs`
    itself: any underscore-fragment appearing on most of THIS catalog's
    own attributes is by definition not a distinguishing word for any
    one of them -- the same "shared parts are never a distinguishing
    fact" reasoning `disambiguated_label` already applies across
    siblings, generalized here to the whole catalog. High threshold
    (>40%) so a genuinely meaningful, merely-common word (e.g. "type")
    is never swept up by this -- only a near-universal catalog-wide
    naming-convention fragment qualifies.
    """
    if not attrs:
        return set()
    _part_counts: dict[str, int] = {}
    for _a in attrs:
        for _p in {p for p in _a.variable_name.lower().split("_") if p}:
            _part_counts[_p] = _part_counts.get(_p, 0) + 1
    _threshold = 0.4 * len(attrs)
    return {p for p, c in _part_counts.items() if c > _threshold}
