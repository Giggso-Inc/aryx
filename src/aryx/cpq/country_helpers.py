"""Country alias-group lookup/normalization and change-request detection,
split out of `cpq/engine.py`'s module-level scope (Phase 4, docs/RAVEN_
STYLE_COMPLIANCE_PLAN_2026-09-03.md -- module-level helper extraction
beyond the 8 previously-deferred methods, done purely to shrink engine.py
further). Re-exported from `aryx.cpq.engine` (see the import there) so
every existing `from aryx.cpq.engine import <name>` caller/test keeps
working unchanged. Logic unchanged from the original inline definitions.
"""

from __future__ import annotations

import re

from aryx.cpq.country_alias_data import _COUNTRY_ALIAS_GROUPS


def _country_alias_group(value: str) -> frozenset[str] | None:
    """The alias group containing `value` (already expected lowercased/
    stripped), or None if it isn't a recognized country name/code in any
    of the 249 real ISO entries + colloquial supplements above. Shared by
    every consumer (auto_fill's hint-priority path, apply_answer's direct-
    reply path) so a fix here closes the gap everywhere at once, instead
    of two independently-drifting copies."""
    for group in _COUNTRY_ALIAS_GROUPS:
        if value in group:
            return group
    return None


def _normalize_country_candidate(value: str) -> str:
    """Lowercase/strip a raw country candidate and collapse the specific
    punctuation ISSUE-007 (docs/CPQ_E2E_ISSUES_001_002_003_004_FIX_PLAN_
    2026_08_17.md) identified as the live bug class -- periods used as
    abbreviation markers ("U.S.A", "US.A", "U.K", "U.A.E") -- down to the
    same plain token `_COUNTRY_ALIAS_GROUPS` already keys on (e.g. "usa",
    "uk", "uae"). Deliberately generic string normalization only (case,
    periods, whitespace) -- never a per-country substitution list, so it
    applies identically to all 249 real countries above, not just the
    US/UK/UAE examples the bug was originally reported against."""
    collapsed = value.strip().lower().replace(".", "")
    return re.sub(r"\s+", " ", collapsed).strip()


def _country_canonical_name(group: frozenset[str]) -> str:
    """Pick a human-readable canonical common name out of an alias group,
    generically -- never a per-country hardcoded lookup table.

    Every group is a flat, unordered frozenset mixing alpha-2 (2 chars),
    alpha-3 (3 chars), common name, and official name -- the original
    pycountry generation order isn't preserved once the data became a
    frozenset. Codes are always <=3 chars by ISO 3166-1 construction;
    every common/official name in this table is longer than that. Among
    whatever's left after dropping the codes, the common name is
    reliably the SHORTEST remaining member, since official names are
    always longer superset phrasings of the common form ("republic of
    X", "kingdom of X", "X of America", ...). Verified against every
    group in `_COUNTRY_ALIAS_GROUPS` (e.g. "united states" beats "united
    states of america"; "south korea" beats "korea, republic of"; "ivory
    coast" beats "republic of côte d'ivoire") -- this function's logic
    never names a specific country."""
    candidates = [member for member in group if len(member) > 3] or list(group)
    return min(candidates, key=len).title()


# Verb-anchored country CHANGE command, mirroring _QUANTITY_CHANGE_VERB_RE's
# shape but scoped to "country" -- descriptive-phrasing detectors elsewhere
# only recognize DESCRIPTIVE phrasing ("customer in X", "destination country
# is X"), never a change COMMAND ("change country to X"), so a customer
# explicitly asking to change the country mid-session had no detector at all
# before this (docs/CPQ_QUANTITY_COUNTRY_SUMMARY_FIXES_2026_08_13.md
# follow-up -- live bug: "Change country to United States unless the
# quantity is 10" fell through to the generic attribute-disambiguation
# clarify prompt instead of ever being recognized as a country-change
# request). The negative lookahead keeps this from firing on an unrelated
# change command that merely happens to mention "country" later in a
# longer sentence about something else entirely -- "country" must appear
# within a short span of the verb.
_COUNTRY_CHANGE_RE = re.compile(
    r"(?i:\b(?:change|set|update|make\s+it)\b(?:(?!\b(?:quantity|qty)\b).){0,25}?"
    r"\bcountry\b\s+(?:to|as|is)\s+)"
    r"((?:[A-Z]{2}|[A-Z][a-z]+)(?:\s+[A-Z][a-z]+)*)"
)


def detect_country_change_request(question: str) -> str | None:
    """Deterministic detector for an explicit "change country to X" command.

    Returns the as-typed, validated country name (e.g. "United States"),
    or None when no verb-anchored country-change command is present, or
    the captured text isn't a country the engine actually recognizes
    (`CpqEngine.is_recognized_country`) -- never a bare regex fragment.
    """
    from aryx.cpq import engine as _engine_module

    m = _COUNTRY_CHANGE_RE.search(question or "")
    if not m:
        return None
    candidate = m.group(1).strip()
    if not _engine_module.CpqEngine.is_recognized_country(candidate):
        return None
    return candidate
