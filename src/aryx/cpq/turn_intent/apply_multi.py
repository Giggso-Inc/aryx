"""``apply_multi_answer`` -- resolve a user's free-text/menu-option answer(s)
for a multi-select attribute (Phase 4 step 2 extraction from
``cpq/engine.py``, see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).
Stateless -- needs no engine-instance callback.
"""

from __future__ import annotations

import re

from aryx.cpq.engine import _valid
from aryx.cpq.state import ConfigAttr


def apply_multi_answer(
    attr: ConfigAttr,
    user_answer: str,
    constrained_item_values: list[str] | None = None,
) -> list[tuple[str, str]]:
    """Match ALL option names mentioned in a multi-select answer.

    apply_answer() deliberately returns only the single best match — the
    right behavior for a single-select question. A multi-select answer
    like "Shirt Magnetic Mount, Jacket Magnetic Mount, ..." names several
    options at once; using apply_answer() alone silently keeps only one
    (confirmed live: naming all 6 real mounting-type options in one
    answer captured just 1). This scans for every option whose display
    name appears in the answer, consuming matched text so a shorter
    option name already covered by a longer one isn't double-counted
    (e.g. "TEK-LOK Belt Mount" vs "Belt Mount").

    Returns a list of (item_value, display_name) pairs, in the order
    their names appear in the answer text — empty if none matched.
    """
    allowed = set(constrained_item_values) if constrained_item_values is not None else None
    options = (
        [o for o in attr.options if o.item_value in allowed]
        if allowed is not None else attr.options
    )
    ua = user_answer.lower()
    remaining = ua
    matches: list[tuple[int, str, str]] = []  # (position, item_value, display_name)
    for opt in sorted(options, key=lambda o: len(o.display_name), reverse=True):
        if not _valid(opt.item_value):
            continue
        dn = opt.display_name.lower()
        if not dn:
            continue
        pattern = re.compile(r"(?<!\w)" + re.escape(dn) + r"(?!\w)")
        m = pattern.search(remaining)
        if m:
            matches.append((m.start(), opt.item_value, opt.display_name))
            # Blank out the matched span so a shorter, overlapping option
            # name (already covered by this longer match) can't also match.
            remaining = remaining[:m.start()] + " " * (m.end() - m.start()) + remaining[m.end():]
    matches.sort(key=lambda t: t[0])
    return [(iv, dn) for _pos, iv, dn in matches]
