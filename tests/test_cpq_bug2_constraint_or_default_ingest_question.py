"""docs/CPQ_BUG2_CONSTRAINT_DISPATCH_MISCLASSIFICATION_IMPLEMENTATION_PLAN_2026-08-14.md (v2)

_load_value_rules previously treated EVERY multi-value, set_type != -1
declarative action as "ambiguous which ONE default", asking a human "which
one is the default?" -- a question that was incoherent for all 21 real
rules of this shape (every one targets a multi-select field, verified live;
"pick exactly one" was never a valid framing).

v1 of this fix tried to auto-classify via the target's select_type. Verified
live against real data (apx-cpq-test workspace 12 + workspace 19, 62 real
rows) that select_type is 100% "multi" across the WHOLE set -- zero
variance, no signal. Same for BM's own constraint-shaped fields
(constrain_all/constraint_type/filter_attribute/action_type/value_type) --
identical across every real action row. No structural signal exists.

v2 (this fix): keep detection exactly as before (same condition, dynamic,
no rule names/IDs anywhere) but ask the RIGHT question via a new ingest-
question kind ("cpq_multivalue_constraint_or_default") with two answers:
'constraint' -> narrow to these values (ConstraintRule, same mechanism
set_type==-1 already uses) or 'assign_all' -> blocked (RecommendationRule
doesn't support multi-value assignment yet -- state.py:111 is a single
str), never silently guessed either way.
"""
from __future__ import annotations

from unittest.mock import patch

from aryx.cpq.engine import CpqEngine
from aryx.cpq.state import ConstraintRule, RecommendationRule


class _FakeRdb:
    """Same minimal double as test_cpq_valueless_hide_actions.py."""

    def __init__(self, value_rules, inputs=(), actions=(), scripts=None):
        self._value_rules = value_rules
        self._inputs = list(inputs)
        self._actions = list(actions)
        self._scripts = scripts or {}

    def fetch_value_rules(self, workspace_id, catalog_prefix="", active_only=False):
        return self._value_rules

    def fetch_rule_inputs(self, workspace_id, catalog_prefix=""):
        return [row if len(row) == 4 else (*row, "4") for row in self._inputs]

    def fetch_rule_actions(self, workspace_id, catalog_prefix=""):
        return self._actions

    def fetch_marked_attrs(self, workspace_id, catalog_prefix=""):
        return []

    def fetch_rule_chain_links(self, workspace_id, catalog_prefix=""):
        return []

    def fetch_function_scripts(self, workspace_id, catalog_prefix=""):
        return self._scripts

    def fetch_rules(self, workspace_id, rule_type, catalog_prefix="", active_only=False):
        return []


def _load(fake_rdb, existing_questions=None):
    class _FakeStore:
        def __init__(self, rows):
            self._rows = rows

        def list(self, workspace_id, status=""):
            return self._rows

        def enqueue(self, workspace_id, job_id, kind, prompt, options=None,
                    suggested=""):
            self.last_enqueue = {
                "workspace_id": workspace_id, "job_id": job_id, "kind": kind,
                "prompt": prompt, "options": options, "suggested": suggested,
            }
            return 1

    store = _FakeStore(existing_questions or [])
    with patch("aryx.cpq.engine.get_cpq_rdb", return_value=fake_rdb), \
         patch("aryx.cpq.engine.IngestQuestionStore", return_value=store):
        result = CpqEngine()._load_value_rules(1, "")
    return result, store


def test_multivalue_action_with_no_answer_enqueues_constraint_or_default_question():
    """Detection is unchanged from before (same trigger condition) -- but the
    question asked, and its kind, must be the corrected one, not the old
    'which one is the default' framing."""
    fake_rdb = _FakeRdb(
        value_rules=[(500, 500, "Default Frequency Band MSL if Multi Band Selected", "1", -1)],
        inputs=[(500, 1, "APX NEXT MULTI")],
        actions=[(500, 2, 1, "UHF~VHF~700/800 MHZ", -1, 2, "System recommendation")],
    )
    (rec_rules, con_rules, _val, _hid), store = _load(fake_rdb)
    assert rec_rules == []
    assert con_rules == []
    assert hasattr(store, "last_enqueue")
    enq = store.last_enqueue
    assert enq["kind"] == "cpq_multivalue_constraint_or_default"
    assert enq["options"] == ["constraint", "assign_all"]
    assert "which" not in enq["prompt"].lower() or "narrow" in enq["prompt"].lower()
    assert "NARROW" in enq["prompt"]
    assert "ASSIGN" in enq["prompt"]


def test_answered_constraint_becomes_constraint_rule():
    """A human answering 'constraint' must resolve to a ConstraintRule with
    the original candidate values as allowed_values -- same runtime path
    set_type==-1 already uses (apply_constraint_rules is provenance-
    agnostic)."""
    fake_rdb = _FakeRdb(
        value_rules=[(500, 500, "Default Frequency Band MSL if Multi Band Selected", "1", -1)],
        inputs=[(500, 1, "APX NEXT MULTI")],
        actions=[(500, 2, 1, "UHF~VHF~700/800 MHZ", -1, 2, "System recommendation")],
    )
    existing = [{
        "job_id": "cpq-rule-500-2-constraint-or-default",
        "status": "answered", "answer": "constraint",
    }]
    (rec_rules, con_rules, _val, _hid), _store = _load(fake_rdb, existing)
    assert rec_rules == []
    assert len(con_rules) == 1
    rule = con_rules[0]
    assert isinstance(rule, ConstraintRule)
    assert rule.target_attr_id == 2
    assert rule.allowed_values == ["UHF", "VHF", "700/800 MHZ"]


def test_answered_constraint_is_case_and_whitespace_insensitive():
    """Raven review of PR #198 -- an answer of 'Constraint' (or with stray
    whitespace) must still resolve correctly, not fall through to the
    unrecognized-answer path just because of case/whitespace."""
    fake_rdb = _FakeRdb(
        value_rules=[(500, 500, "Default Frequency Band MSL if Multi Band Selected", "1", -1)],
        inputs=[(500, 1, "APX NEXT MULTI")],
        actions=[(500, 2, 1, "UHF~VHF~700/800 MHZ", -1, 2, "System recommendation")],
    )
    existing = [{
        "job_id": "cpq-rule-500-2-constraint-or-default",
        "status": "answered", "answer": "  Constraint  ",
    }]
    (rec_rules, con_rules, _val, _hid), store = _load(fake_rdb, existing)
    assert rec_rules == []
    assert len(con_rules) == 1
    assert con_rules[0].allowed_values == ["UHF", "VHF", "700/800 MHZ"]
    assert not hasattr(store, "last_enqueue")


def test_unrecognized_answer_auto_requeues_a_fresh_question():
    """Raven review of PR #198 -- a malformed/garbage answer (not
    'constraint' or 'assign_all') must NOT permanently strand the rule with
    only a manual DB fix as recovery. A fresh, distinctly-numbered question
    must be automatically enqueued so the rule remains answerable, without
    touching or reusing the stale answered row."""
    fake_rdb = _FakeRdb(
        value_rules=[(500, 500, "Default Frequency Band MSL if Multi Band Selected", "1", -1)],
        inputs=[(500, 1, "APX NEXT MULTI")],
        actions=[(500, 2, 1, "UHF~VHF~700/800 MHZ", -1, 2, "System recommendation")],
    )
    existing = [{
        "job_id": "cpq-rule-500-2-constraint-or-default",
        "status": "answered", "answer": "maybe??",
    }]
    (rec_rules, con_rules, _val, _hid), store = _load(fake_rdb, existing)
    assert rec_rules == []
    assert con_rules == []
    assert hasattr(store, "last_enqueue"), (
        "an unrecognized answer must trigger a fresh, pending question -- "
        "not leave the rule permanently stuck"
    )
    enq = store.last_enqueue
    assert enq["job_id"] == "cpq-rule-500-2-constraint-or-default-r2", (
        "the fresh question must use a distinct job_id in the same chain, "
        "never the stale answered one"
    )
    assert enq["kind"] == "cpq_multivalue_constraint_or_default"


def test_unrecognized_answer_on_a_retry_requeues_the_next_one_in_chain():
    """If the LATEST question in the chain (not just the original) was also
    answered with garbage, the next chain link gets minted -- not a
    collision back onto an already-stuck job_id."""
    fake_rdb = _FakeRdb(
        value_rules=[(500, 500, "Default Frequency Band MSL if Multi Band Selected", "1", -1)],
        inputs=[(500, 1, "APX NEXT MULTI")],
        actions=[(500, 2, 1, "UHF~VHF~700/800 MHZ", -1, 2, "System recommendation")],
    )
    existing = [
        {"job_id": "cpq-rule-500-2-constraint-or-default",
         "status": "answered", "answer": "nope"},
        {"job_id": "cpq-rule-500-2-constraint-or-default-r2",
         "status": "answered", "answer": "still wrong"},
    ]
    (rec_rules, con_rules, _val, _hid), store = _load(fake_rdb, existing)
    assert rec_rules == []
    assert con_rules == []
    assert store.last_enqueue["job_id"] == "cpq-rule-500-2-constraint-or-default-r3"


def test_answered_assign_all_is_blocked_not_applied():
    """A human answering 'assign_all' must NOT produce a RecommendationRule
    -- RecommendationRule.recommended_value is single-valued (state.py:111),
    so this is logged as blocked, never partially applied or guessed."""
    fake_rdb = _FakeRdb(
        value_rules=[(600, 600, "Set Values for Software Bundle", "1", -1)],
        inputs=[(600, 1, "CORE BUNDLE")],
        actions=[(600, 3, 1, "FEATURE A~FEATURE B~FEATURE C", -1, 2, "System recommendation")],
    )
    existing = [{
        "job_id": "cpq-rule-600-3-constraint-or-default",
        "status": "answered", "answer": "assign_all",
    }]
    (rec_rules, con_rules, _val, _hid), _store = _load(fake_rdb, existing)
    assert rec_rules == []
    assert con_rules == []


def test_multivalue_action_already_pending_does_not_reenqueue():
    """An unanswered, already-queued question must not be re-enqueued on
    every load -- same convention the old ambiguous-recommendation branch
    used."""
    fake_rdb = _FakeRdb(
        value_rules=[(700, 700, "Some Rule", "1", -1)],
        inputs=[(700, 1, "X")],
        actions=[(700, 4, 1, "A~B~C", -1, 2, "System recommendation")],
    )
    existing = [{
        "job_id": "cpq-rule-700-4-constraint-or-default", "status": "pending",
    }]
    (rec_rules, con_rules, _val, _hid), store = _load(fake_rdb, existing)
    assert rec_rules == []
    assert con_rules == []
    assert not hasattr(store, "last_enqueue")


def test_single_value_action_still_a_plain_recommendation():
    """Sanity check: the pre-existing single-candidate path (len(parts)==1)
    is unaffected -- still a plain RecommendationRule, no question asked."""
    fake_rdb = _FakeRdb(
        value_rules=[(800, 800, "Default Hardware Version", "1", -1)],
        inputs=[(800, 1, "NA")],
        actions=[(800, 5, 1, "NEXT STANDARD LTE ONLY", -1, 2, "System recommendation")],
    )
    (rec_rules, con_rules, _val, _hid), store = _load(fake_rdb)
    assert con_rules == []
    assert len(rec_rules) == 1
    assert isinstance(rec_rules[0], RecommendationRule)
    assert rec_rules[0].recommended_value == "NEXT STANDARD LTE ONLY"
    assert not hasattr(store, "last_enqueue")
