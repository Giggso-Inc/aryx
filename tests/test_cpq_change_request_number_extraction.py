"""Free-text quantity change-request number extraction.

Raven review finding (M1): detect_change_request's free-text branch pulled
the FIRST standalone number anywhere in the message, not the one after the
change verb. This catalog's own product names embed digits (V200 Body Worn
Camera, APX6500 — both confirmed live elsewhere in this codebase), so
"change the V200 Body Worn Camera quantity to 2" matched "200" (from the
product name) before the intended "2" — a silent wrong-value fill the
customer would have to notice and manually correct. Fix: anchor to the
"to"/"from" verb pattern first, falling back to the original greedy search
only when no directional verb is present.

Follow-up Raven review finding: anchoring to "to"/"from" still searched the
WHOLE message, so a message naming two sibling quantity attrs (SVX's own
per-mount-type quantity attrs are all named "mounting type {Mount Name}
Quantity", one per mount option) had both attrs' searches independently
grab the SAME first "to N" in the sentence — whichever attr `attrs`
iteration reached first won, regardless of which number was actually meant
for it (confirmed live by reversing iteration order). Fix: scope the search
to the text between THIS attr's own label mention and the next sibling
attr's mention (if any), via `_label_mention_span`.
"""
from __future__ import annotations

from aryx.cpq.engine import CpqEngine
from aryx.cpq.state import ConfigAttr


def _qty_attr(variable_name: str, display_label: str) -> ConfigAttr:
    return ConfigAttr(
        entity_id=1, variable_name=variable_name, display_label=display_label,
        required=False, default_value="", select_type="single", options=[],
    )


def test_product_name_digit_no_longer_wins_over_the_real_quantity():
    """The exact regression case: the attr's own label embeds a digit
    sequence ('V200') that a greedy digit-search would grab before the
    real intended quantity."""
    engine = CpqEngine()
    attr = _qty_attr("v200BodyWornCameraQuantity_viSoln", "V200 Body Worn Camera Quantity")
    result = engine.detect_change_request(
        "Change the V200 Body Worn Camera quantity to 2",
        [attr], filled={"v200BodyWornCameraQuantity_viSoln": "1"},
    )

    assert result is not None
    assert result[0].variable_name == "v200BodyWornCameraQuantity_viSoln"
    assert result[1] == "2", "must extract the value after 'to', not the '200' embedded in the product name"


def test_apx_model_code_digit_no_longer_wins_over_the_real_quantity():
    engine = CpqEngine()
    attr = _qty_attr("apx6500Quantity_astro", "APX 6500 Quantity")
    result = engine.detect_change_request(
        "Change the APX 6500 quantity to 3",
        [attr], filled={"apx6500Quantity_astro": "1"},
    )

    assert result is not None
    assert result[1] == "3", "must extract the value after 'to', not the '6500' embedded in the model code"


def test_generic_label_does_not_shadow_a_more_specific_one_it_subsumes():
    # Confirmed live (SVX, workspace 19): "Change the mounting type Locking
    # Molle Mount Quantity to 10" matched the generic
    # accecsssoriesQuantityArray_viSoln (real label "Quantity") instead of
    # mountingTypeLockingMolleMountQuantity_viSoln (real label "mounting
    # type Locking Molle Mount Quantity") — purely because the generic attr
    # happened to sit earlier in catalog order. "Quantity" is a literal
    # substring of the specific label, so it must be deprioritized.
    engine = CpqEngine()
    generic = _qty_attr("accecsssoriesQuantityArray_viSoln", "Quantity")
    specific = _qty_attr(
        "mountingTypeLockingMolleMountQuantity_viSoln",
        "mounting type Locking Molle Mount Quantity",
    )
    filled = {
        "accecsssoriesQuantityArray_viSoln": "1",
        "mountingTypeLockingMolleMountQuantity_viSoln": "7",
    }
    result = engine.detect_change_request(
        "Change the mounting type Locking Molle Mount Quantity to 10.",
        [generic, specific], filled=filled,
    )

    assert result is not None
    assert result[0].variable_name == "mountingTypeLockingMolleMountQuantity_viSoln", (
        "the specific, fully-mentioned label must win over the generic "
        "substring label it subsumes"
    )
    assert result[1] == "10"


def test_sibling_labels_that_dont_subsume_each_other_keep_order_dependent_result():
    # Regression guard: two independent sibling labels (neither a substring
    # of the other) must NOT be reordered by the subsumption fix — the
    # existing "whichever attr the caller lists first, if both would
    # independently match" contract stays intact.
    engine = CpqEngine()
    jacket = _qty_attr(
        "mountingTypeJacketMagneticMountQuantity_viSoln",
        "mounting type Jacket Magnetic Mount Quantity")
    pouch = _qty_attr(
        "mountingTypePouchMountQuantity_viSoln",
        "mounting type Pouch Mount Quantity")
    filled = {
        "mountingTypeJacketMagneticMountQuantity_viSoln": "1",
        "mountingTypePouchMountQuantity_viSoln": "1",
    }
    question = "change the jacket magnetic mount quantity to 15 and the pouch mount quantity to 8"

    result_pouch_first = engine.detect_change_request(question, [pouch, jacket], filled=filled)
    assert result_pouch_first[0].variable_name == pouch.variable_name


def test_from_verb_also_anchors_correctly():
    engine = CpqEngine()
    attr = _qty_attr("v200BodyWornCameraQuantity_viSoln", "V200 Body Worn Camera Quantity")
    result = engine.detect_change_request(
        "change the V200 Body Worn Camera quantity from 1 to 4",
        [attr], filled={"v200BodyWornCameraQuantity_viSoln": "1"},
    )

    assert result is not None
    assert result[1] == "4", "when both 'from' and 'to' are present, the 'to' value wins (checked first)"


def test_no_directional_verb_falls_back_to_original_greedy_search():
    """No 'to'/'from' phrasing present — preserves the original,
    pre-existing behavior rather than failing to extract anything."""
    engine = CpqEngine()
    attr = _qty_attr("jacketMagneticMountQuantity_viSoln", "Jacket Magnetic Mount Quantity")
    result = engine.detect_change_request(
        "change the jacket magnetic mount quantity, make it 15",
        [attr], filled={"jacketMagneticMountQuantity_viSoln": "1"},
    )

    assert result is not None
    assert result[1] == "15"


def test_two_sibling_quantity_attrs_each_get_their_own_number():
    """The exact collision regression: two sibling quantity attrs named in
    one message must each resolve to the number nearest their OWN mention,
    regardless of which attr `attrs` iteration order reaches first."""
    engine = CpqEngine()
    jacket = _qty_attr(
        "mountingTypeJacketMagneticMountQuantity_viSoln",
        "mounting type Jacket Magnetic Mount Quantity")
    pouch = _qty_attr(
        "mountingTypePouchMountQuantity_viSoln",
        "mounting type Pouch Mount Quantity")
    filled = {
        "mountingTypeJacketMagneticMountQuantity_viSoln": "1",
        "mountingTypePouchMountQuantity_viSoln": "1",
    }
    question = (
        "change the jacket magnetic mount quantity to 15 "
        "and the pouch mount quantity to 8"
    )

    result_jacket_first = engine.detect_change_request(question, [jacket, pouch], filled=filled)
    assert result_jacket_first[0].variable_name == jacket.variable_name
    assert result_jacket_first[1] == "15"

    result_pouch_first = engine.detect_change_request(question, [pouch, jacket], filled=filled)
    assert result_pouch_first[0].variable_name == pouch.variable_name
    assert result_pouch_first[1] == "8", (
        "must extract the number nearest pouch's own mention (8), not "
        "jacket's number (15) just because it appears earlier in the message"
    )


def test_unchanged_value_is_not_reported_as_a_change():
    engine = CpqEngine()
    attr = _qty_attr("v200BodyWornCameraQuantity_viSoln", "V200 Body Worn Camera Quantity")
    result = engine.detect_change_request(
        "change the V200 Body Worn Camera quantity to 2",
        [attr], filled={"v200BodyWornCameraQuantity_viSoln": "2"},
    )

    assert result is None


def test_reordered_phrase_still_matches_dropping_the_generic_prefix_too():
    """docs/CPQ_SESSION_2_OPEN_ISSUES.md item 1: a message stating the
    quantity BEFORE the mount name — reversed from the label's own
    "...Jacket Magnetic Mount Quantity" word order — while ALSO dropping
    the generic "mounting type" prefix in the same breath, previously fell
    through to no match at all (neither the drop-leading-words tier nor a
    naive order-blind full-word-set check succeeds, since the dropped
    prefix words are never in a reordered message and the leftover words
    are out of order). `_label_mention_span`'s word-set fallback now tries
    progressively shorter leading-word-dropped suffixes as an order-blind
    SET, closing this gap without weakening the "match fully or bail"
    contract for any individual candidate."""
    engine = CpqEngine()
    attr = _qty_attr(
        "mountingTypeJacketMagneticMountQuantity_viSoln",
        "mounting type Jacket Magnetic Mount Quantity")
    filled = {"mountingTypeJacketMagneticMountQuantity_viSoln": "10"}

    result = engine.detect_change_request(
        "change the quantity of jacket magnetic mount to 15", [attr], filled=filled,
    )
    assert result is not None
    assert result[0].variable_name == attr.variable_name
    assert result[1] == "15"

    # A genuinely ambiguous message (no specific mount named at all) must
    # still decline rather than guess which sibling attr is meant.
    pouch = _qty_attr(
        "mountingTypePouchMountQuantity_viSoln", "mounting type Pouch Mount Quantity")
    filled_both = {**filled, "mountingTypePouchMountQuantity_viSoln": "3"}
    ambiguous = engine.detect_change_request(
        "change the mounting type quantity to 15", [attr, pouch], filled=filled_both,
    )
    assert ambiguous is None, (
        "a message naming no specific mount type must never guess which "
        "sibling attr was meant")


def test_arrow_notation_works_without_a_recognized_change_verb():
    # Confirmed live (SVX, workspace 19): "chnage mounting type Jacket
    # Magnetic Mount Quantity → 89" has NO word _CHANGE_VERB_RE recognizes
    # (the typo "chnage" doesn't contain "chang"), so the entire free-text
    # number-extraction branch never ran, producing "I didn't quite catch
    # that." An arrow ("→"/"->") is unambiguous "set to" notation on its
    # own and must trigger the same detection path as a real verb.
    engine = CpqEngine()
    attr = _qty_attr(
        "mountingTypeJacketMagneticMountQuantity_viSoln",
        "mounting type Jacket Magnetic Mount Quantity")
    filled = {"mountingTypeJacketMagneticMountQuantity_viSoln": "66"}

    result = engine.detect_change_request(
        "chnage mounting type Jacket Magnetic Mount Quantity → 89",
        [attr], filled=filled,
    )
    assert result is not None
    assert result[0].variable_name == attr.variable_name
    assert result[1] == "89"


def test_ascii_arrow_notation_also_works():
    engine = CpqEngine()
    attr = _qty_attr(
        "mountingTypeJacketMagneticMountQuantity_viSoln",
        "mounting type Jacket Magnetic Mount Quantity")
    filled = {"mountingTypeJacketMagneticMountQuantity_viSoln": "66"}

    result = engine.detect_change_request(
        "mounting type Jacket Magnetic Mount Quantity -> 89", [attr], filled=filled,
    )
    assert result is not None
    assert result[1] == "89"
