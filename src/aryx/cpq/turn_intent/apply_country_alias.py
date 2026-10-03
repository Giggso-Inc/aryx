"""Country-alias fallback for ``apply.apply_answer``, split off purely
to keep both files under the file-size cap (Phase 4,
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md). No logic changed.
"""

from __future__ import annotations

from aryx.cpq.engine import _country_alias_group, _valid, logger
from aryx.cpq.state import ConfigAttr, MenuOption
from aryx.log_safe import text_ref


def country_alias_fallback(
    attr: ConfigAttr, user_answer: str, ua: str, options: list[MenuOption],
) -> tuple[str, str] | None:
    """A direct reply naming a country by a DIFFERENT alias than the
    option's own item_value/display_name (e.g. "USA" replying to an
    attr whose real option is item_value="US", display_name="United
    States") previously fell through every check above to a hard miss
    with no logging at all (confirmed live 2026-08-14: Ultimate
    Destination Country accepted "US" via the exact item_value check
    above but rejected "USA"). Uses `_country_alias_group` -- the same
    249-real-country, bidirectional alias table auto_fill's hint-
    priority path uses -- so a fix to the underlying data closes the
    gap in both places at once. Narrow and safe -- only fires when
    `ua` (the whole trimmed reply) exactly equals a known alias, never
    a substring/fuzzy guess.
    """
    alias_group = _country_alias_group(ua)
    if not alias_group:
        return None
    for opt in options:
        if (opt.item_value.lower() in alias_group
                or opt.display_name.lower() in alias_group):
            if _valid(opt.item_value):
                logger.info(
                    "cpq_apply_answer_alias_match attr=%s reply=%s "
                    "resolved_to=%r",
                    attr.variable_name, text_ref(user_answer), opt.item_value,
                )
                return opt.item_value, opt.display_name
    return None
