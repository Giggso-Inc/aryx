"""ISO-3166-1 country alias data table, split out of `cpq/engine.py`'s
module-level scope (Phase 4, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.
md -- module-level helper extraction beyond the 8 previously-deferred
methods, done purely to shrink engine.py further). Re-exported from
`aryx.cpq.engine` (see the import there) so every existing `from
aryx.cpq.engine import <name>` caller/test keeps working unchanged.

_COUNTRY_ALIAS_GROUPS is data-generated (not hand-typed) from pycountry's
ISO 3166-1 tables -- one frozenset per real country containing its
common name, official name, alpha-2, and alpha-3 codes -- plus a small,
explicit set of colloquial names ISO's own name fields don't carry but
real customers type constantly (uk, uae, russia, vatican, ivory coast,
swaziland, macedonia, micronesia, burma, turkey, palestine, brunei).
pycountry itself is NOT a runtime dependency of this project -- it was
used ONLY offline, once, to generate this literal. Regenerate by
re-running the same generation script if pycountry's ISO data is ever
updated upstream.

Every group is symmetric by construction: `_country_alias_group("usa")`
and `_country_alias_group("us")` both return the identical frozenset
containing "united states", "us", "usa", "united states of america".

Split across `country_alias_data_a.py`/`country_alias_data_b.py` (a
mechanical line-count split of one literal tuple, no semantic grouping)
purely to keep each file under the manifest's 150-line-per-file cap --
this combining module concatenates them back into one public constant.
"""

from __future__ import annotations

from aryx.cpq.country.country_alias_data_a import _COUNTRY_ALIAS_GROUPS_A
from aryx.cpq.country.country_alias_data_b import _COUNTRY_ALIAS_GROUPS_B

_COUNTRY_ALIAS_GROUPS: tuple[frozenset[str], ...] = (
    _COUNTRY_ALIAS_GROUPS_A + _COUNTRY_ALIAS_GROUPS_B
)
