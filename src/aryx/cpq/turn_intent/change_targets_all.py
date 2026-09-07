"""``detect_all_change_targets_without_value`` -- every already-filled attr
named in a valueless change utterance (Phase 4 step 2 extraction from
``cpq/engine.py``, see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).
Stateless -- needs no engine-instance callback.
"""

from __future__ import annotations

from aryx.cpq.state import ConfigAttr
from aryx.cpq.turn_intent.patterns import _CHANGE_VERB_RE


def detect_all_change_targets_without_value(
    question: str,
    attrs: list[ConfigAttr],
    filled: dict[str, str],
    *,
    filled_multi: dict[str, list[str]] | None = None,
    exclude_vns: set[str] | None = None,
    cap: int = 10,
) -> list[ConfigAttr]:
    """All already-filled attrs named in a valueless change utterance.

    Ordered by first appearance of the label/vn in the question so
    "change hardware version, service type and activation delay"
    yields a stable FIFO for pending_intent_queue. ``exclude_vns``
    skips already-handled targets; ``cap`` bounds the scan (default
    matches INTENT_QUEUE_CAP).
    """
    if not _CHANGE_VERB_RE.search(question or ""):
        return []
    exclude = exclude_vns or set()
    multi = filled_multi or {}
    q_flat = (question or "").lower().replace("_", " ")
    matches: list[ConfigAttr] = []
    for a in attrs:
        if a.variable_name in exclude:
            continue
        if not (filled.get(a.variable_name) or multi.get(a.variable_name)):
            continue
        label_l = (a.display_label or "").lower()
        vn_flat = a.variable_name.lower().replace("_", " ")
        # Full label, variable_name, or a trailing multi-word slice of
        # the label (e.g. "service type" matching "Primary Service Type").
        hit = False
        if label_l and label_l in q_flat:
            hit = True
        elif vn_flat and vn_flat in q_flat:
            hit = True
        else:
            words = [w for w in label_l.split() if len(w) > 1]
            for n in range(min(len(words), 3), 1, -1):
                tail = " ".join(words[-n:])
                if tail in q_flat:
                    hit = True
                    break
        if hit:
            matches.append(a)
    # Prefer longer labels when one subsumes another (same as singular
    # detector's max-by-len), but keep appearance order among peers.
    # First drop subsumed shorter labels that share the same span.
    def _pos(a: ConfigAttr) -> int:
        label_l = (a.display_label or "").lower()
        vn_flat = a.variable_name.lower().replace("_", " ")
        positions = [i for i in (
            q_flat.find(label_l) if label_l else -1,
            q_flat.find(vn_flat) if vn_flat else -1,
        ) if i >= 0]
        return min(positions) if positions else 9999

    # Drop attrs whose label is a strict substring of another match's
    # label at the same region (e.g. "Type" inside "Service Type") —
    # keep the longest label at each position cluster.
    matches.sort(key=lambda a: (-len(a.display_label or ""), _pos(a), a.variable_name))
    kept: list[ConfigAttr] = []
    kept_labels: list[str] = []
    for a in matches:
        lab = (a.display_label or "").lower()
        if any(lab and lab != k and lab in k for k in kept_labels):
            continue
        kept.append(a)
        kept_labels.append(lab)
    # Stable user-facing order: appearance in the utterance.
    kept.sort(key=_pos)
    return kept[: max(0, cap)]
