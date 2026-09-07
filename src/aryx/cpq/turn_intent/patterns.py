"""Turn-intent regex patterns cluster (Phase 4 step 2 extraction from
``cpq/engine.py`` -- see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md).

Presentation/approval/change-verb detector patterns -- split from
``patterns2.py`` purely to keep both files under the file-size cap; no
thematic distinction beyond that.
"""

from __future__ import annotations

import re

# §6.1/§6.2 explicit-request detectors — shared "did the client ask for a
# different presentation" pattern. Biased toward returning None (the rich
# default: verbose narrative, one question at a time) on ambiguity — a
# false negative just stays verbose; a false positive leaks JSON or a
# batch dump the client didn't ask for.
_JSON_REQUEST_RE = re.compile(
    r"\b(show|give|see|what'?s)\b[^.?!]{0,30}\b(json|payload|bom)\b|"
    r"\bjson\b[^.?!]{0,20}\b(so\s+far|now|please)\b",
    re.IGNORECASE,
)
_BATCH_REQUEST_RE = re.compile(
    r"\bwhat\s+else\b|\bwhat'?s\s+left\b|"
    r"\bshow\s+(me\s+)?(all|everything)\b|"
    r"\blist\s+(all|the)\s+(remaining|pending)\b|"
    r"\bwhat\s+do\s+you\s+(still\s+)?need\b",
    re.IGNORECASE,
)

# Approval keywords — user is confirming the configuration (Step 8 trigger)
_APPROVAL_RE = re.compile(
    r"^(?:i\s+(?:hereby\s+|just\s+|really\s+)?)?"
    r"(yes|confirm(?:ed)?|approve(?:d)?|submit|finali[sz]e|"
    r"looks?\s+good|that'?s?\s+(correct|right|good|it)|go\s+ahead|"
    r"proceed|ok(?:ay)?|all\s+good|send\s+it|let'?s?\s+go)\b|"
    r"^(?:great|perfect)\b[\s,!.]*(?:let'?s?\s+go|that'?s?\s+(?:works|good|right))?$",
    re.IGNORECASE,
)

# Q&A intent signals — user is asking a question, not answering a config prompt
#
# "list the/all/available"/"show me the/all/available" added
# 2026-08-31 — live-confirmed gap: "list the attributes in APX Next"
# starts with neither a "?" nor any of the original leading words, so
# detect_qa_question returned False both during active configuration
# (strict=True) and awaiting_approval review (strict=False), falling
# through to change-request detection instead of ever reaching
# _handle_cpq_qa's whole-catalog enumeration matcher (docs/
# CPQ_QA_Catalog_Attribute_Listing_Fix_2026_08_31.md).
#
# Deliberately NOT a bare `list\b`/`show\s+me\b` (Raven Review
# finding, 2026-08-31): unlike the pre-quote enumeration matcher in
# ask_api.py, which double-checks a keyword match against an LLM
# classification call before treating anything as a whole-catalog
# request, THIS regex is the sole gate for QA-vs-change-request
# routing turn-wide — a bare `list` would wrongly route a genuine
# imperative change request like "list Hardware Version as APX NEXT"
# into Q&A instead of change-request handling (the mirror-image of
# the bug this fix closes). Requiring an article after the verb
# ("the"/"all"/"available") keeps it matching only genuine
# enumeration phrasing, which a "set this to that" change command
# does not naturally produce.
_QA_INTENT_RE = re.compile(
    r"^(what|why|how|explain|tell\s+me|describe|what'?s?\s*(is|are)?|"
    r"difference\s+between|compare|which\s+is\s+(better|best)|"
    r"can\s+you\s+explain|why\s+can'?t|how\s+does|how\s+do|"
    r"list\s+(the|all|available)|show\s+me\s+(the|all|available))\b",
    re.IGNORECASE,
)

# Change-request verbs — user wants to modify a filled attr (Step 6 cascade).
# Conjugated forms ("-ing", "-e") are included so "i am changing" / "switching"
# / "replacing" all fire has_change_verb=True and activate the attr-name guard.
_CHANGE_VERB_RE = re.compile(
    r"\b(choos(?:e|ing)|select(?:ing)?|pick(?:ing)?|"
    r"swapp?(?:ing)?|chang(?:e|ing)|switch(?:ing)?|replac(?:e|ing)|"
    r"updat(?:e|ing)|modif(?:y|ying)|actually|instead|"
    r"make\s+it|i\s+want|use\s+.+\s+instead)\b",
    re.IGNORECASE,
)
# An arrow ("→" or "->") is unambiguous "set this to that" notation on
# its own — confirmed live: "chnage mounting type Jacket Magnetic Mount
# Quantity → 89" has NO word _CHANGE_VERB_RE recognizes (the typo
# "chnage" doesn't contain "chang"), so has_change_verb was False and
# the entire free-text number-extraction branch below never ran at all.
# Rather than attempt general typo-tolerance (fuzzy, risky — this
# engine's "never guess" discipline), the arrow itself is treated as an
# equally strong, unambiguous change signal — same tier as a real verb.
_ARROW_RE = re.compile(r"->|→")

# Removal verbs — user wants to DESELECT an already-chosen multi-select
# option, not add a new one (docs: Ask page needs to let a customer
# deselect a mount type, not just add more). Deliberately distinct from
# _CHANGE_VERB_RE: "change X to Y" replaces a single-select's value,
# while "remove X" subtracts one option from an existing multi-select
# selection — different verbs, different target data structure
# (filled_multi, never filled).
_REMOVE_VERB_RE = re.compile(
    r"\b(remove|deselect|de-select|delete|drop|uncheck|take\s+out|"
    r"get\s+rid\s+of|don'?t\s+need)\b",
    re.IGNORECASE,
)
