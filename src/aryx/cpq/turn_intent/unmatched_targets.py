"""``detect_unmatched_change_targets`` -- plain-language leftover clauses
from a change message that named nothing real (Phase 4 step 2 extraction
from ``cpq/engine.py``, see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).
Stateless -- needs no engine-instance callback.
"""

from __future__ import annotations

import re

from aryx.cpq.engine import _label_mentioned_strict
from aryx.cpq.state import ConfigAttr
from aryx.cpq.turn_intent.patterns import _ARROW_RE, _CHANGE_VERB_RE
from aryx.cpq.turn_intent.patterns2 import _GENERIC_CLAUSE_STOPWORDS


def detect_unmatched_change_targets(
    question: str,
    attrs: list[ConfigAttr],
    matched_vns: "set[str]",
) -> list[str]:
    """Live-verified gap (2026-07-28): "change solution type and
    hardware type" — where "hardware type" names nothing real in this
    catalog (it's "Hardware Version", not "Hardware Type") — silently
    dropped "hardware type" entirely once "solution type" was
    successfully matched. The customer explicitly asked for two
    things and only saw one addressed, with no indication the second
    wasn't understood — indistinguishable from the system just
    forgetting it.

    Returns plain-language leftover phrases from the message that
    (a) weren't accounted for by any attr already in `matched_vns`,
    (b) don't match ANY real attr's label either (a genuine second
    VALID target — just one this caller hasn't resolved yet — is not
    "unmatched", it's simply not this function's problem), and
    (c) share at least one content word with SOME real catalog
    label, the signal that this was a plausible-but-failed naming
    attempt rather than an unrelated trailing clause ("...and
    confirm") that happens to split on the same connective.

    Deliberately conservative: only runs when the message has an
    actual change-verb AND a connective ("and"/","/"&") joining
    multiple clauses — a single-clause message has nothing "left
    over" to flag by construction.
    """
    verb_match = _CHANGE_VERB_RE.search(question) or _ARROW_RE.search(question)
    if not verb_match:
        return []
    if not re.search(r"\band\b|,|&", question, re.IGNORECASE):
        return []
    catalog_words: set[str] = set()
    for a in attrs:
        catalog_words |= set(re.findall(r"[a-z0-9]+", a.display_label.lower()))
    clauses = re.split(r"\band\b|,|&", question, flags=re.IGNORECASE)
    unmatched: list[str] = []
    for clause in clauses:
        clause = clause.strip()
        if not clause:
            continue
        clause_lower = clause.lower()
        # Already accounted for by an attr this caller DID match.
        if any(
            a.variable_name in matched_vns
            and _label_mentioned_strict(a.display_label.lower(), clause_lower)
            for a in attrs
        ):
            continue
        # Names a REAL attr — just not (yet) one in matched_vns. Not
        # this function's concern; a genuine second valid target is
        # not the same failure as naming nothing at all.
        if any(_label_mentioned_strict(a.display_label.lower(), clause_lower) for a in attrs):
            continue
        stripped = _CHANGE_VERB_RE.sub("", clause, count=1).strip()
        stripped = _ARROW_RE.sub("", stripped, count=1).strip()
        if not stripped or len(stripped.split()) > 6:
            continue
        clause_words = (
            set(re.findall(r"[a-z0-9]+", stripped.lower()))
            - _GENERIC_CLAUSE_STOPWORDS
        )
        if clause_words & catalog_words:
            unmatched.append(stripped)
    return unmatched
