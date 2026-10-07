"""Two structural "hide unless present in a master delimited list" BML
idioms (C and D) — a different shape from the if/else-if/else chain
`bml_branches._parse_branches` parses.

Split out of `cpq/bml.py` (Raven Style Compliance Plan, Phase 2a,
2026-09-03). See `bml_text.py`'s docstring for the zero-patch-risk basis.
"""
from __future__ import annotations

import re


# Idiom C — "hide unless present in a master delimited list": a shape
# distinct from the if/else-if/else chain _first_matching_branch parses —
# one guarded if-block, no branch-vs-branch comparison at all. Found live
# investigating Amendment 18's 121 hiding-rule targets that fell through to
# Tier 2 despite depending on nothing but two already-filled variables — the
# grammar, not missing data, was the blocker. Confirmed identical shape
# across dozens of real rules in the CommandCentral Aware catalog (e.g.
# "Hide Third Party Vendor Name if no values available", "Hide QTY Included
# array if not values are available", "Hide Connector Type Included array if
# not values are available", ...), differing only in which master/separator
# variable and which literal name they check for:
#
#   if(MASTER<>""){
#   ARR = SPLIT(MASTER,SEP);
#   IDX = findinarray(ARR,"LITERAL");
#      if (IDX ==-1){
#          return TRUE;
#      }
#      }
#   return FALSE;
#
# Semantics: hide the target UNLESS "LITERAL" appears in MASTER's own value
# once split on SEP's own value (an empty/missing MASTER never hides — the
# outer guard is false, so it falls straight to `return FALSE`).
# `re.fullmatch` (not `search`) against the whole comment-stripped script:
# anything beyond this exact shape bails to None rather than guessing.
_COMMENT_RE = re.compile(r'/\*.*?\*/', re.DOTALL)
_HIDE_MASTER_LIST_RE = re.compile(
    r'if\s*\(\s*(?P<master>\w+)\s*<>\s*""\s*\)\s*\{\s*'
    r'(?P<arr>\w+)\s*=\s*SPLIT\s*\(\s*(?P=master)\s*,\s*(?P<sep>\w+)\s*\)\s*;\s*'
    r'(?P<idx>\w+)\s*=\s*findinarray\s*\(\s*(?P=arr)\s*,\s*"(?P<literal>[^"]*)"\s*\)\s*;\s*'
    r'if\s*\(\s*(?P=idx)\s*==\s*-1\s*\)\s*\{\s*'
    r'return\s+true\s*;\s*'
    r'\}\s*'
    r'\}\s*'
    r'return\s+false\s*;\s*',
    re.IGNORECASE,
)
# Same shape, but the index variable that is TESTED is not the one that was ASSIGNED (live: ws 1267 has 3,225 hide
# scripts that assign `lindex = findinarray(...)` and test `valindex ==-1`). Only used when the caller opts in.
_HIDE_MASTER_LIST_ALIAS_RE = re.compile(_HIDE_MASTER_LIST_RE.pattern.replace(r'(?P=idx)\s*==', r'(?P<tested>\w+)\s*=='),
                                        re.IGNORECASE)


def _aliased(m: "re.Match[str] | None", variables: dict[str, str]) -> "re.Match[str] | None":
    """The loose match, only when the tested index name is not a real variable (an unassigned index stands for the
    findinarray result)."""
    if m is None or m.group("tested") in variables or m.group("tested") == m.group("idx"):
        return None
    return m


def evaluate_hide_master_list(
    script: str, variables: dict[str, str], alias_unassigned_index: bool = False,
) -> tuple[bool | None, bool]:
    """Tier 1.5 (Idiom C): resolve the "hide unless in master list" idiom
    deterministically. Returns (hide, blocked_by_missing_var) — same
    contract as evaluate_hide_tier1/_first_matching_branch. (None, False)
    means the script isn't this idiom at all (try the next tier); (None,
    True) means it IS this idiom but MASTER or SEP isn't filled yet.
    """
    text = _COMMENT_RE.sub("", script).strip()
    m = _HIDE_MASTER_LIST_RE.fullmatch(text)
    if not m and alias_unassigned_index:
        m = _aliased(_HIDE_MASTER_LIST_ALIAS_RE.fullmatch(text), variables)
    if not m:
        return None, False
    master = variables.get(m.group("master"))
    sep = variables.get(m.group("sep"))
    if master is None or sep is None:
        return None, True
    if master == "":
        return False, False
    return m.group("literal") not in master.split(sep), False

# Idiom D — the ungated sibling of Idiom C: no outer `if(MASTER<>"")` guard
# at all, and an extra nested base-model check inside the else branch.
# Confirmed live shape of Carrier Selection / Wireless Carrier's real
# hiding-rule scripts (docs/CPQ_CARRIER_WIRELESS_FREQBAND_DATA_GAP_PROOF_
# 2026_08_07.md §1.3/§2.3):
#
#   ARR = SPLIT(MASTER, SEP);
#   IDX = findinarray(ARR, "LITERAL");
#   if (IDX == -1) {
#       return true;
#   }
#   else {
#       if (BASEMODEL == "") {
#           return true;
#       }
#   }
#   return false;
#
# Neither Idiom C's regex (requires the outer guard) nor
# _first_matching_branch's if/else-if/else chain parser (built for
# branch-vs-branch comparisons, not a nested nullary SPLIT/findinarray)
# recognize this shape — it previously fell through both to Tier 2 (LLM),
# which has no reason to know an empty MASTER here means "Oracle's runtime
# master-string sync was never captured for this catalog" rather than "no
# entry, confidently hide". Reporting a confident hide silently dropped the
# attribute before it ever reached the real ingested Data Table fallback
# (data_table_resolver.py) that DOES have rows for it in this catalog.
_HIDE_MASTER_LIST_UNGUARDED_RE = re.compile(
    r'(?P<arr>\w+)\s*=\s*SPLIT\s*\(\s*(?P<master>\w+)\s*,\s*(?P<sep>\w+)\s*\)\s*;\s*'
    r'(?P<idx>\w+)\s*=\s*findinarray\s*\(\s*(?P=arr)\s*,\s*"(?P<literal>[^"]*)"\s*\)\s*;\s*'
    r'if\s*\(\s*(?P=idx)\s*==\s*-1\s*\)\s*\{\s*'
    r'return\s+true\s*;\s*'
    r'\}\s*'
    r'else\s*\{\s*'
    r'if\s*\(\s*(?P<basemodel>\w+)\s*==\s*""\s*\)\s*\{\s*'
    r'return\s+true\s*;\s*'
    r'\}\s*'
    r'\}\s*'
    r'return\s+false\s*;\s*',
    re.IGNORECASE,
)


_HIDE_MASTER_LIST_UNGUARDED_ALIAS_RE = re.compile(
    _HIDE_MASTER_LIST_UNGUARDED_RE.pattern.replace(r'(?P=idx)\s*==', r'(?P<tested>\w+)\s*=='), re.IGNORECASE)


def evaluate_hide_master_list_unguarded(
    script: str, variables: dict[str, str], trust_empty_master: bool = False, alias_unassigned_index: bool = False,
) -> tuple[bool | None, bool]:
    """Tier 1.5 (Idiom D). Returns (hide, blocked_by_missing_var) — same
    contract as the other Tier-1 evaluators. (None, False) means the
    script isn't this idiom (try the next tier). An empty/unset MASTER
    reports (None, True) — blocked/unknown — NOT a confident hide, since
    (unlike Idiom C) there is no outer guard making that the script's own
    deterministic answer; here it's genuinely missing runtime data. An
    empty BASEMODEL, by contrast, is a real "nothing selected yet" state
    (same convention used everywhere else in this codebase) and DOES
    report a confident hide.
    """
    text = _COMMENT_RE.sub("", script).strip()
    m = _HIDE_MASTER_LIST_UNGUARDED_RE.fullmatch(text)
    if not m and alias_unassigned_index:
        m = _aliased(_HIDE_MASTER_LIST_UNGUARDED_ALIAS_RE.fullmatch(text), variables)
    if not m:
        return None, False
    master = variables.get(m.group("master"))
    sep = variables.get(m.group("sep"))
    if master is None or sep is None:
        return None, True
    if master == "" and not trust_empty_master:
        return None, True
    # trust_empty_master (plan F9): the caller COMPUTED the master string, so
    # "" is authoritative -- the literal is not in it and the script hides.
    if m.group("literal") not in master.split(sep):
        return True, False
    base_model = variables.get(m.group("basemodel"))
    if base_model is None:
        return None, True
    if base_model == "":
        return True, False
    return False, False
