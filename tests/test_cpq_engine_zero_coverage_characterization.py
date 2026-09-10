"""Golden-master characterization tests for 5 `CpqEngine`/`engine.py`
functions confirmed (by direct-name grep across the whole test suite, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md "Phase 4 planning analysis")
to have ZERO direct test coverage before this file: `is_cpq_question`,
`detect_response_mode_request`, `find_rule_inconsistencies`,
`build_context_sentence`, `detect_country_change_request`.

Written as step 1 of Phase 4 (the golden-master safety net required before
any future code-splitting of `cpq/engine.py`, which the plan's own
analysis found should eventually be split under 150 lines per file). These
tests pin CURRENT behavior only — nothing here is a spec of "correct"
behavior, and no bug found while reading the code is fixed here. Any
surprising or inconsistent behavior found is documented in the affected
test's own docstring instead, per this codebase's established
characterization-test convention (see e.g. tests/test_datasources_
characterization.py's "Known pre-existing bugs" pattern referenced in the
same plan doc).
"""
from __future__ import annotations

from unittest.mock import patch

from aryx.cpq.engine import CpqEngine, detect_country_change_request
from aryx.cpq.state import ConfigAttr, MenuOption
from aryx.cpq.state.state_rules import ConstraintRule, HidingRule, RecommendationRule


def _menu(*vals: str) -> list[MenuOption]:
    return [MenuOption(item_value=v, display_name=v, order=i) for i, v in enumerate(vals, start=1)]


def _attr(entity_id, vn, label=None, *, options=None, required=False,
          default="", select_type="single", source_id=None) -> ConfigAttr:
    return ConfigAttr(
        entity_id=entity_id, variable_name=vn, display_label=label or vn,
        required=required, default_value=default, options=options or [],
        select_type=select_type, source_id=source_id,
    )


# ═══════════════════════════════════════════════════════════════════════
# detect_country_change_request (module-level function)
# ═══════════════════════════════════════════════════════════════════════

def test_recognizes_change_command_with_full_country_name():
    assert detect_country_change_request("make it country to Canada") == "Canada"


def test_recognizes_set_and_update_verbs_too():
    assert detect_country_change_request("set country as UK") == "UK"
    # NOTE (characterization, not a fix): "Deutschland" is captured by the
    # regex but is not a recognized alias in this engine's 249-country
    # table, so the whole detector returns None -- a real German-language
    # country name is silently unrecognized just like a typo would be.
    assert detect_country_change_request("update country is Deutschland") is None


def test_two_letter_allcaps_candidate_is_truncated_to_two_chars():
    """Documented pre-existing quirk, NOT fixed here: the capture group's
    all-caps alternative is `[A-Z]{2}` (exactly two letters), so a 3+
    letter all-caps country token like "USA" only ever captures its first
    two characters. "change country to USA" -> "US", not "USA" -- this
    happens to still validate (US is a real alpha-2 code) so the bug is
    silent rather than a rejected match, but the returned text is not what
    the customer actually typed."""
    assert detect_country_change_request("please change country to USA now") == "US"


def test_returns_the_as_typed_candidate_not_the_canonical_resolved_name():
    """Documented characterization detail: despite the docstring's own
    example ("United States"), this function returns `candidate` (the
    literal captured text) rather than `CpqEngine.is_recognized_country`'s
    resolved canonical value -- it only uses that method as a validation
    gate, never taking its return value. A country typed as an
    already-canonical string round-trips fine; a non-canonical alias would
    not be canonicalized here."""
    assert detect_country_change_request("change country to United States") == "United States"


def test_quantity_word_inside_the_change_span_blocks_the_match():
    """The negative lookahead in _COUNTRY_CHANGE_RE rejects "quantity"/"qty"
    appearing between the change verb and "country" -- even when "country"
    genuinely appears later in the same clause."""
    assert detect_country_change_request("change the quantity country to Mexico") is None


def test_plain_quantity_change_is_not_mistaken_for_a_country_change():
    assert detect_country_change_request("change qty to 10") is None


def test_no_change_verb_present_returns_none():
    """Descriptive phrasing ("customer in France") is NOT a change command
    -- this detector requires an anchoring verb (change/set/update/make it)."""
    assert detect_country_change_request("the customer is in France") is None


def test_unrecognized_country_text_returns_none():
    assert detect_country_change_request("change country to Wakanda") is None


def test_empty_and_none_question_return_none():
    assert detect_country_change_request("") is None
    assert detect_country_change_request(None) is None


def test_own_region_code_na_is_excluded_even_though_syntactically_valid():
    """"NA" is this system's own North America region token as well as
    Namibia's real ISO alpha-2 code -- the documented single collision
    exclusion in is_recognized_country makes this detector return None
    rather than silently treating a NA/EMEA/APAC-style token as a country."""
    assert detect_country_change_request("change country to NA") is None


def test_change_verb_variants_all_recognized():
    for verb_phrase in ("change country to Japan", "set country to Japan",
                        "update country to Japan", "make it country to Japan"):
        assert detect_country_change_request(verb_phrase) == "Japan"


# ═══════════════════════════════════════════════════════════════════════
# CpqEngine.is_cpq_question
# ═══════════════════════════════════════════════════════════════════════

class _FakeCatalogReader:
    """Minimal reader double for the dynamic ingested-product lookup,
    following the same _FakeProductReader shape already established in
    tests/test_cpq_product_switch.py (reused here rather than inventing a
    new double)."""

    def __init__(self, catalogs: dict[str, str], trees: dict[str, list[str]] | None = None):
        self._catalogs = catalogs
        self._trees = trees or {}
        self.id_to_name: dict[int, str] = {}
        self._next_id = 1000

    def distinct_types(self):
        return [f"{prefix}BmConfigAttr" for prefix in self._catalogs]

    def _ent(self, ontology_type: str, pname: str) -> dict:
        self._next_id += 1
        eid = self._next_id
        self.id_to_name[eid] = pname
        return {"id": eid, "type": ontology_type, "name": pname}

    def find_entities(self, ontology_type=None, name=None, limit=50, offset=0):
        for prefix, pname in self._catalogs.items():
            if ontology_type == f"{prefix}BmPrdFamily":
                return [self._ent(ontology_type, pname)]
            if ontology_type == f"{prefix}BmCatalog":
                return [self._ent(ontology_type, t) for t in self._trees.get(prefix, [])]
        return []


class _NoDistinctTypesReader:
    """A reader double lacking distinct_types entirely -- exercises the
    AttributeError branch of both _ingested_product_names and
    ingested_product_alias_map."""


def _patched_engine(reader: _FakeCatalogReader):
    engine = CpqEngine()
    patcher = patch.object(
        CpqEngine, "_batch_fetch",
        lambda self, ids, ws: {i: {"name": reader.id_to_name.get(i, "")} for i in ids},
    )
    return engine, patcher


def test_generic_cpq_vocabulary_matches_without_any_reader():
    """The fixed-English-word trigger regex is checked first and short-
    circuits everything else -- reader=None never matters when it hits."""
    eng = CpqEngine()
    assert eng.is_cpq_question("I'd like to configure a quote", None) is True


def test_generic_vocabulary_words_cover_radios_and_bom_and_carrier():
    eng = CpqEngine()
    assert eng.is_cpq_question("tell me about radios", None) is True
    assert eng.is_cpq_question("what's in the bom", None) is True
    assert eng.is_cpq_question("which carrier do you support", None) is True


def test_non_cpq_question_with_no_reader_returns_false():
    eng = CpqEngine()
    assert eng.is_cpq_question("what's the weather today", None) is False


def test_empty_question_is_never_cpq():
    eng = CpqEngine()
    assert eng.is_cpq_question("", None) is False


def test_dynamic_product_family_name_recognized_via_reader():
    reader = _FakeCatalogReader({"ApxConfig": "aSTRO25_bom"})
    engine, patcher = _patched_engine(reader)
    with patcher:
        assert engine.is_cpq_question("tell me about aSTRO25_bom please", reader, 1) is True


def test_dynamic_customer_facing_alias_name_recognized_via_catalog_tree():
    """The live-confirmed gap the docstring documents: a real customer-
    facing name ("APX Next") that is NOT the internal family code must
    still be recognized, via ingested_product_alias_map's catalog-tree
    aliases, not just _ingested_product_names' family names."""
    reader = _FakeCatalogReader(
        {"ApxConfig": "aSTRO25_bom"}, trees={"ApxConfig": ["APX Next", "aPXNext_BOM"]},
    )
    engine, patcher = _patched_engine(reader)
    with patcher:
        assert engine.is_cpq_question(
            "I want to order APX Next radios for my department", reader, 1,
        ) is True


def test_short_alias_fragment_below_min_phrase_len_does_not_match():
    """_HINT_MIN_PHRASE_LEN=5 -- a normalized candidate shorter than that
    (here "APX", normalizing to 3 chars) is deliberately never matched,
    even though it IS a real substring of the question, to avoid
    over-triggering on short, common fragments."""
    reader = _FakeCatalogReader(
        {"ApxConfig": "aSTRO25_bom"}, trees={"ApxConfig": ["APX Next", "aPXNext_BOM"]},
    )
    engine, patcher = _patched_engine(reader)
    with patcher:
        assert engine.is_cpq_question("APX", reader, 1) is False


def test_reader_without_distinct_types_falls_back_to_false():
    """AttributeError from the reader (both _ingested_product_names and
    ingested_product_alias_map) is swallowed and treated as "no dynamic
    candidates available", never an exception escaping is_cpq_question."""
    eng = CpqEngine()
    reader = _NoDistinctTypesReader()
    assert eng.is_cpq_question("hello, anybody selling anything here", reader, 1) is False


def test_question_with_no_alnum_characters_short_circuits_before_reader_lookup():
    """q_norm ends up empty ("" after stripping non-alnum) -> returns False
    immediately, without ever calling ingested_product_alias_map."""
    reader = _FakeCatalogReader({"ApxConfig": "aSTRO25_bom"})
    engine, patcher = _patched_engine(reader)
    with patcher:
        assert engine.is_cpq_question("!!! ???", reader, 1) is False


# ═══════════════════════════════════════════════════════════════════════
# CpqEngine.detect_response_mode_request
# ═══════════════════════════════════════════════════════════════════════

def test_json_request_phrasings_return_json():
    eng = CpqEngine()
    assert eng.detect_response_mode_request("can you show me the json") == "json"
    assert eng.detect_response_mode_request("give me the payload") == "json"
    assert eng.detect_response_mode_request("json please") == "json"


def test_batch_request_phrasings_return_batch():
    eng = CpqEngine()
    assert eng.detect_response_mode_request("what else do you need") == "batch"
    assert eng.detect_response_mode_request("what's left") == "batch"
    assert eng.detect_response_mode_request("show me everything") == "batch"
    assert eng.detect_response_mode_request("what do you still need") == "batch"


def test_plain_conversational_question_returns_none():
    eng = CpqEngine()
    assert eng.detect_response_mode_request("hello there") is None
    assert eng.detect_response_mode_request("") is None


def test_json_check_is_tried_before_batch_when_both_could_match():
    """_JSON_REQUEST_RE.search runs first and returns immediately -- a
    question containing both signals resolves to "json", never "batch"."""
    eng = CpqEngine()
    assert eng.detect_response_mode_request(
        "show me the json and what else is needed",
    ) == "json"


def test_what_is_the_bom_phrasing_is_not_recognized_json_request():
    """Documented characterization gap, NOT fixed here: the JSON regex's
    first alternative requires one of show|give|see|what's (the
    CONTRACTED form) immediately before the bom/json/payload keyword.
    "what is the bom so far" uses the uncontracted "what is" -- neither
    alternative matches, so this returns None even though a customer
    asking about the BOM so far reads as an obvious JSON/payload request
    to a human."""
    eng = CpqEngine()
    assert eng.detect_response_mode_request("what is the bom so far") is None


def test_list_all_the_remaining_phrasing_is_not_recognized_batch_request():
    """Documented characterization gap, NOT fixed here: the batch regex's
    "list (all|the) (remaining|pending)" alternative requires exactly ONE
    of "all"/"the" between "list" and "remaining" -- "list all the
    remaining" has both words ("all the") and matches neither
    alternative, so this natural phrasing returns None."""
    eng = CpqEngine()
    assert eng.detect_response_mode_request("list all the remaining") is None


def test_none_question_raises_type_error():
    """Documented behavioral asymmetry with detect_country_change_request
    (which defensively does `question or ""`): this method calls
    `self._JSON_REQUEST_RE.search(question)` directly with no None guard,
    so passing None raises TypeError rather than returning None. Every
    real caller in ask_api.py always passes a real question string, so
    this has never surfaced in practice -- documented here as a
    characterization fact, not fixed."""
    eng = CpqEngine()
    try:
        eng.detect_response_mode_request(None)
        raised = False
    except TypeError:
        raised = True
    assert raised, "expected detect_response_mode_request(None) to raise TypeError"


# ═══════════════════════════════════════════════════════════════════════
# CpqEngine.find_rule_inconsistencies
# ═══════════════════════════════════════════════════════════════════════

def _rule_fixture():
    flavor = _attr(1, "flavor", "Flavor", options=_menu("A", "B"), required=True)
    hidden_target = _attr(2, "hiddenTarget", "Hidden Target", options=_menu("X", "Y"))
    rec_target = _attr(3, "recTarget", "Rec Target", options=_menu("X", "Y"))
    con_target = _attr(4, "conTarget", "Con Target", options=_menu("X", "Y", "Z"))
    attrs = [flavor, hidden_target, rec_target, con_target]
    hiding = HidingRule(rule_name="hide when A", condition_attr_id=1,
                         condition_value="A", target_attr_id=2, hide=True)
    rec = RecommendationRule(rule_name="rec when B", condition_attr_id=1,
                              condition_value="B", target_attr_id=3, recommended_value="Y")
    con = ConstraintRule(rule_name="con when B", condition_attr_id=1,
                          condition_value="B", target_attr_id=4, allowed_values=["Y"])
    return attrs, hiding, rec, con


def test_empty_everything_returns_no_issues():
    eng = CpqEngine()
    assert eng.find_rule_inconsistencies({}, [], [], [], []) == []


def test_flags_a_filled_attr_that_an_active_hiding_rule_now_matches():
    attrs, hiding, rec, con = _rule_fixture()
    eng = CpqEngine()
    filled = {"flavor": "A", "hiddenTarget": "X", "recTarget": "X", "conTarget": "Z"}
    issues = eng.find_rule_inconsistencies(filled, attrs, [hiding], [con], [rec])
    assert issues == [{
        "attr": "hiddenTarget", "value": "X", "rule_type": "hiding",
        "issue": "filled but an active hiding rule matches",
    }]


def test_flags_a_value_no_longer_in_the_active_constrained_set():
    attrs, hiding, rec, con = _rule_fixture()
    eng = CpqEngine()
    filled = {"flavor": "B", "recTarget": "Y", "conTarget": "Z"}
    issues = eng.find_rule_inconsistencies(filled, attrs, [], [con], [rec])
    assert issues == [{
        "attr": "conTarget", "value": "Z", "rule_type": "constraint",
        "issue": "value not in active allowed set ['Y']",
    }]


def test_flags_a_recommendation_condition_met_but_value_disagrees():
    attrs, hiding, rec, con = _rule_fixture()
    eng = CpqEngine()
    filled = {"flavor": "B", "recTarget": "X", "conTarget": "Y"}
    issues = eng.find_rule_inconsistencies(
        filled, attrs, [], [con], [rec], filled_source={"recTarget": "default"},
    )
    assert issues == [{
        "attr": "recTarget", "value": "X", "rule_type": "recommendation",
        "issue": "condition met but value != recommended 'Y'",
    }]


def test_a_user_sourced_recommendation_disagreement_is_not_flagged():
    """The docstring's explicit contract: a deliberate customer override is
    never an inconsistency, even against a currently-satisfied
    recommendation."""
    attrs, hiding, rec, con = _rule_fixture()
    eng = CpqEngine()
    filled = {"flavor": "B", "recTarget": "X", "conTarget": "Y"}
    issues = eng.find_rule_inconsistencies(
        filled, attrs, [], [con], [rec], filled_source={"recTarget": "user"},
    )
    assert issues == []


def test_multiple_simultaneous_issues_are_all_reported():
    attrs, hiding, rec, con = _rule_fixture()
    eng = CpqEngine()
    filled = {"flavor": "B", "recTarget": "X", "conTarget": "Z"}
    issues = eng.find_rule_inconsistencies(
        filled, attrs, [], [con], [rec], filled_source={"recTarget": "default"},
    )
    rule_types = {i["rule_type"] for i in issues}
    assert rule_types == {"constraint", "recommendation"}
    assert len(issues) == 2


def test_script_backed_recommendation_rule_is_skipped_without_a_bml_evaluator():
    """Docstring contract: "a rule whose script outcome is 'unknown' is
    simply skipped" -- a script-backed rule with bml_eval=None (the
    default) can never be evaluated, so it never contributes an issue,
    never raises."""
    flavor = _attr(1, "flavor", "Flavor", options=_menu("A", "B"), required=True)
    rec_target = _attr(3, "recTarget", "Rec Target", options=_menu("X", "Y"))
    rec = RecommendationRule(
        rule_name="scripted rec", condition_attr_id=1, condition_value="",
        target_attr_id=3, recommended_value="", script="if (flavor == 'B') { return 'Y'; }",
    )
    eng = CpqEngine()
    filled = {"flavor": "B", "recTarget": "X"}
    issues = eng.find_rule_inconsistencies(
        filled, [flavor, rec_target], [], [], [rec], bml_eval=None,
    )
    assert issues == []


def test_a_rule_targeting_an_attr_not_currently_filled_is_ignored():
    attrs, hiding, rec, con = _rule_fixture()
    eng = CpqEngine()
    filled = {"flavor": "B"}  # recTarget/conTarget never filled at all
    issues = eng.find_rule_inconsistencies(
        filled, attrs, [], [con], [rec], filled_source={},
    )
    assert issues == []


# ═══════════════════════════════════════════════════════════════════════
# CpqEngine.build_context_sentence
# ═══════════════════════════════════════════════════════════════════════

def _context_fixture():
    flavor = _attr(1, "flavor", "Flavor", options=_menu("A", "B"), required=True)
    target = _attr(2, "target", "Target Attr", options=_menu("X", "Y"))
    return flavor, target


def test_show_type_hiding_rule_produces_the_reveal_sentence():
    flavor, target = _context_fixture()
    show_rule = HidingRule(rule_name="show rule", condition_attr_id=1,
                            condition_value="B", target_attr_id=2, hide=False)
    eng = CpqEngine()
    sentence = eng.build_context_sentence(
        target, [flavor, target], {"flavor": "B"}, {"flavor": "B-Display"},
        [show_rule], [],
    )
    assert sentence == "Since we locked in **B-Display**, please choose the **Target Attr**."


def test_falls_back_to_raw_filled_value_when_display_filled_has_no_entry():
    flavor, target = _context_fixture()
    show_rule = HidingRule(rule_name="show rule", condition_attr_id=1,
                            condition_value="B", target_attr_id=2, hide=False)
    eng = CpqEngine()
    sentence = eng.build_context_sentence(
        target, [flavor, target], {"flavor": "B"}, {}, [show_rule], [],
    )
    assert sentence == "Since we locked in **B**, please choose the **Target Attr**."


def test_hide_type_rules_are_never_used_to_explain_a_pending_question():
    """`rule.hide` truthy is explicitly skipped (`continue`) -- a HIDE rule
    targeting this attr must never surface as its "why are you asking
    this" explanation, even if it structurally matches."""
    flavor, target = _context_fixture()
    hide_rule = HidingRule(rule_name="hide rule", condition_attr_id=1,
                            condition_value="B", target_attr_id=2, hide=True)
    eng = CpqEngine()
    sentence = eng.build_context_sentence(
        target, [flavor, target], {"flavor": "B"}, {}, [hide_rule], [],
    )
    assert sentence == ""


def test_recommendation_rule_used_when_no_hiding_rule_matches():
    flavor, target = _context_fixture()
    rec_rule = RecommendationRule(rule_name="rec", condition_attr_id=1,
                                   condition_value="B", target_attr_id=2, recommended_value="Y")
    eng = CpqEngine()
    sentence = eng.build_context_sentence(
        target, [flavor, target], {"flavor": "B"}, {}, [], [rec_rule],
    )
    assert sentence == "Since we locked in **B**, please choose the **Target Attr**."


def test_hiding_rule_checked_before_recommendation_rule_when_both_would_match():
    flavor, target = _context_fixture()
    show_rule = HidingRule(rule_name="show rule", condition_attr_id=1,
                            condition_value="B", target_attr_id=2, hide=False)
    rec_rule = RecommendationRule(rule_name="rec", condition_attr_id=1,
                                   condition_value="B", target_attr_id=2, recommended_value="Y")
    eng = CpqEngine()
    sentence = eng.build_context_sentence(
        target, [flavor, target], {"flavor": "B"}, {"flavor": "Bee"},
        [show_rule], [rec_rule],
    )
    assert sentence == "Since we locked in **Bee**, please choose the **Target Attr**."


def test_condition_attr_not_yet_filled_yields_empty_sentence():
    flavor, target = _context_fixture()
    show_rule = HidingRule(rule_name="show rule", condition_attr_id=1,
                            condition_value="B", target_attr_id=2, hide=False)
    eng = CpqEngine()
    assert eng.build_context_sentence(target, [flavor, target], {}, {}, [show_rule], []) == ""


def test_no_matching_rule_at_all_yields_empty_sentence():
    """An independently-required attr with no rule relationship at all --
    the documented "" default return."""
    flavor, target = _context_fixture()
    eng = CpqEngine()
    assert eng.build_context_sentence(target, [flavor, target], {"flavor": "B"}, {}, [], []) == ""


def test_matches_via_source_id_when_pending_attrs_own_entity_id_differs():
    """pending_attr.source_id is added to `pending_ids` alongside its
    entity_id -- a rule authored against the BM-native source id (rather
    than the aryx-assigned entity_id) still resolves correctly."""
    flavor = _attr(1, "flavor", "Flavor", options=_menu("A", "B"), required=True)
    target_with_source_id = _attr(99, "target2", "Target2", source_id=2)
    show_rule = HidingRule(rule_name="show rule via source_id", condition_attr_id=1,
                            condition_value="B", target_attr_id=2, hide=False)
    eng = CpqEngine()
    sentence = eng.build_context_sentence(
        target_with_source_id, [flavor, target_with_source_id],
        {"flavor": "B"}, {}, [show_rule], [],
    )
    assert sentence == "Since we locked in **B**, please choose the **Target2**."
