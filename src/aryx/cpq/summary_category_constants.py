"""Summary-grouping category tables for `render_filled_summary`/
`categorized_summary_groups`, split out of `cpq/engine.py`'s module-level
scope (Phase 4, docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md --
module-level constant extraction, done purely to shrink engine.py
further). Re-exported from `aryx.cpq.engine` (see the import there) so
every existing `from aryx.cpq.engine import <name>` caller/test, and
`summary_display_formatting`'s `_engine_module.<name>` whole-module-
reference reads, keep working unchanged. Logic unchanged from the
original inline definitions.
"""

from __future__ import annotations

# Generic across any ingested catalog: never a literal per-catalog field
# name (e.g. "modelSelectionSelectModel_viSoln" or "serviceType_astro"),
# only the fragment every catalog's own naming happens to share
# ("model"/"product", "service"/"billing"/"plan", "quantity"/"duration").
# Checked in this fixed order — the first category whose fragments match
# wins, so "serviceDuration_astro" (Service Plan fragment "service"
# checked before "duration") lands in Service Plan, not Quantity &
# Duration, matching how a sales rep would actually group it.
_SUMMARY_CATEGORY_KEYS: tuple[tuple[str, tuple[str, ...]], ...] = (
    # Narrow, specific fragments only — "model" alone is too broad: both
    # catalogs prefix MANY unrelated attrs with "modelSelection*" (frequency
    # bands, keypad type, display type share APX's naming convention with
    # its actual model/product attr), so a loose "model" substring sweeps
    # those in too. These fragments target the attr that names the product
    # itself, not siblings that merely share its naming prefix.
    # "hwversion" added live-verified (2026-07-24): hWVersion_astro matched
    # none of the original fragments, so it fell into the fallback
    # "Associated Options" category — which the LLM narrator is explicitly
    # allowed to only PARTIALLY cover (never claims completeness, by
    # design, to avoid hallucinated placeholders for omitted facts). That
    # meant a customer's own explicit "change the hardware version to X"
    # could silently vanish from the "Configuration complete" summary even
    # though the JSON payload had it correctly — a real product-identifying
    # decision deserves the same always-fully-shown treatment as Base
    # Model/Product Name, not partial-coverage treatment.
    ("Product Name", ("selectmodel", "basemodel", "modelname", "productname",
                       "productselection", "producttype", "hwversion")),
    ("Service Plan", ("service", "billing", "plan", "solutiontype", "archetype")),
    ("Quantity & Duration", ("quantity", "duration", "qty")),
)
_SUMMARY_FALLBACK_CATEGORY = "Associated Options"

# Curated "business-relevant" fragments for the catch-all Associated
# Options section ONLY — Product Name/Service Plan/Quantity & Duration
# stay unaffected (already narrow by category definition). Generic
# technical/customer-facing configuration dimensions common across every
# catalog this engine has ingested (APX NEXT, SVX, DM4400, SL3500e) — a
# sales rep would actually read these out loud. Deliberately excludes
# internal/administrative fields a rule may well govern but nobody
# customer-facing cares about (validation org, order type, software
# release, provisioning-agency status, config-process markers, "agency
# has Motorola evidence solution" style CRM context) — narrower than
# "any rule fired" (product decision, confirmed live: that scope still
# left ~24 largely-administrative items in a real APX NEXT quote).
_ASSOCIATED_OPTIONS_KEY_FRAGMENTS: frozenset[str] = frozenset({
    "frequency", "band", "antenna", "battery", "carrier", "keypad",
    "housing", "channel", "hardware", "video", "mount", "training",
    "wireless", "display", "knob", "packaging", "packing", "spare",
    "endusertype", "coverage", "accidentaldamage", "rsm", "region",
    "color", "voltage", "certification", "connector", "cable", "earpiece",
    "case", "bracket", "screenprotector", "manual", "charger", "power",
})

# Public alias so ask_api can identify the catch-all category by name
# (e.g. to tighten its own narration instructions for it) without a
# private-name cross-module import.
SUMMARY_FALLBACK_CATEGORY = _SUMMARY_FALLBACK_CATEGORY

# Public alias for the real, non-catch-all category names
# (`categorized_summary_groups`'s own grouping) -- Raven review on PR
# #236 (Medium): ask_api's Mandatory-section boundary regex used to
# duplicate these as hardcoded string literals, which would silently
# under-match again if a category were ever renamed or a new one added
# here without updating that copy. Derived directly from
# _SUMMARY_CATEGORY_KEYS (the one place these names are actually
# defined) instead.
SUMMARY_CATEGORY_NAMES = tuple(category for category, _fragments in _SUMMARY_CATEGORY_KEYS)

# Live-confirmed gap (2026-08-19): in the narrowed "sales rep talking
# points" scope (rule_governed_ids supplied), `_filled_summary_triples`
# already narrows its whole item list down to exactly
# `_is_mandatory_input_attr`'s Tier A/B/C set (PR #222) -- but
# `categorized_summary_groups` still buckets any of those items that don't
# match Product Name/Service Plan/Quantity & Duration's fragments under
# the OLD catch-all name, "Associated Options", and `render_filled_summary`
# / `ask_api._cpq_summary_text` still give that category its old "ONE
# short, intentionally-partial plain-text line, free to omit any fact"
# treatment -- appropriate for a genuine grab-bag of cosmetic/accessory
# facts, but every item reaching this bucket in the narrowed scope is now,
# by construction, a confirmed Mandatory User Input fact (e.g. Software
# Release, Ultimate Destination Country) that must be fully and reliably
# listed, never partially narrated. `categorized_summary_groups` renames
# this bucket to `_SUMMARY_MANDATORY_CATEGORY` whenever `rule_governed_ids`
# is supplied; the full-detail-dump scope (rule_governed_ids=None) keeps
# the original "Associated Options" name and one-line rendering unchanged,
# since that scope is NOT narrowed to mandatory-only and can still be a
# genuine 20-50+ item catch-all.
_SUMMARY_MANDATORY_CATEGORY = "Mandatory User Input"
