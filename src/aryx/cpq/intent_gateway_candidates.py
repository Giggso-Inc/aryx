"""Attribute/value candidate building for the CPQ intent gateway's LLM prompt.

Split out of `cpq/intent_gateway.py` (Raven Style Compliance Plan, Phase 2a,
2026-09-03). None of these functions call `get_settings()`/`_pinned_chat` —
confirmed via grep against every whitebox patch in `test_cpq_intent_
gateway.py`/`test_cpq_value_candidate_truncation_2026_08_21.py`/`test_cpq_
llm_first_cutover_regression.py` before moving — so no patch-retargeting
risk.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from aryx.cpq.intent_schema import GatewayIntentResult
from aryx.cpq.state import ConfigAttr, CpqSession, MenuOption

_VALUE_CAP = 40
_ATTR_CAP = 60
_WORD_RE = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class ValueCandidate:
    """One selectable value the LLM may reference by index only."""

    index: int
    item_value: str
    display_name: str


@dataclass
class AttrCandidateBundle:
    """Attribute + ordered value candidates for the prompt/validator."""

    attr: ConfigAttr
    values: list[ValueCandidate]


def _rank_value_candidates_by_relevance(
    options: list[MenuOption], q_words: set[str], question_lower: str,
) -> list[MenuOption]:
    """Order `options` so values relevant to the customer's message survive
    `_VALUE_CAP`'s truncation, instead of raw catalog/database storage
    order. docs/CPQ_VALUE_CANDIDATE_TRUNCATION_PLAN_2026_08_21.md.

    Live-confirmed bug this closes: a 328-option real catalog attribute
    (Product) truncated to the first 40 in storage order, silently
    excluding a customer-named, exact-match value sitting at index 323-325
    -- the gateway then correctly (from its own truncated view) reported
    the value "not a valid option," degrading to a false disambiguation
    or a discarded-value re-ask.

    Exact matches (case-insensitive, display_name or item_value appearing
    verbatim in the message) always sort first, regardless of score -- the
    single most common trigger of the bug this closes is a customer
    echoing back an option the system itself just displayed, and that
    case gets a guarantee, not just better odds.

    Remaining options are ranked by rarity-weighted word overlap (mirrors
    `ask_api._resolve_target_description`'s scoring -- reused rather than
    a raw overlap count because this codebase already hit and fixed the
    identical failure mode for that scorer: a raw count ties a distinctive
    word to a generic word shared by dozens of labels/options. This
    catalog's own Product list has the same shape -- "APX"/"NEXT" appear
    in dozens of its 328 entries).

    A value with genuinely zero overlap and no exact match is NOT a case
    this function tries to fix -- correctly falling through to a
    clarifying question when no lexical evidence exists is the intended
    behavior, not a gap.
    """
    exact: list[MenuOption] = []
    rest: list[MenuOption] = []
    for o in options:
        display_l = o.display_name.strip().lower()
        value_l = (o.item_value or "").strip().lower()
        # Boundary-aware match, not a bare substring check -- a naive `in`
        # test false-positives on short display names/item_values (e.g.
        # item_value "A" is a substring of "band"), confirmed live while
        # testing this function: every single-letter/short option in a
        # fixture spuriously matched an unrelated message. `\b` alone isn't
        # enough either -- many real display names end in punctuation
        # ("APX NEXT XE (4G LTE+5G)"), and `\b` fails to match at a
        # non-word/non-word boundary (e.g. ")" followed by end-of-string).
        # Lookaround on alphanumeric adjacency handles both cases.
        if (
            (display_l and re.search(
                rf"(?<![a-z0-9]){re.escape(display_l)}(?![a-z0-9])", question_lower))
            or (value_l and re.search(
                rf"(?<![a-z0-9]){re.escape(value_l)}(?![a-z0-9])", question_lower))
        ):
            exact.append(o)
        else:
            rest.append(o)

    vocabs = [set(_WORD_RE.findall(o.display_name.lower())) for o in rest]
    doc_freq: dict[str, int] = {}
    for vocab in vocabs:
        for w in vocab:
            doc_freq[w] = doc_freq.get(w, 0) + 1
    scored = []
    for o, vocab in zip(rest, vocabs):
        overlap = q_words & vocab
        score = sum(1.0 / doc_freq[w] for w in overlap) if overlap else 0.0
        scored.append((score, o))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return exact + [o for _score, o in scored]


def build_candidate_bundles(
    attrs: list[ConfigAttr],
    session: CpqSession,
    question: str,
) -> list[AttrCandidateBundle]:
    """Build attr/value candidates from product config + session state.

    Prefers attributes that are filled, pending, or word-overlap the
    question so the prompt stays bounded on large catalogs.
    """
    q_words = set(_WORD_RE.findall(question.lower()))
    question_lower = question.lower()
    scored: list[tuple[float, ConfigAttr]] = []
    for a in attrs:
        score = 0.0
        if a.variable_name in session.filled or a.variable_name in session.filled_multi:
            score += 5.0
        if session.pending_variables and a.variable_name == session.pending_variables[0]:
            score += 8.0
        if a.variable_name in session.last_qa_variables:
            score += 8.0
        if a.variable_name in session.pending_change_collision_vns:
            score += 7.0
        if a.variable_name == session.pending_change_no_value_vn:
            score += 7.0
        if a.variable_name in session.pending_clarify_vns:
            score += 7.0
        vocab = set(_WORD_RE.findall(a.display_label.lower()))
        vocab |= set(_WORD_RE.findall(a.variable_name.lower().replace("_", " ")))
        ranked_opts_for_vocab = _rank_value_candidates_by_relevance(
            a.options, q_words, question_lower,
        )
        for o in ranked_opts_for_vocab[:_VALUE_CAP]:
            vocab |= set(_WORD_RE.findall(o.display_name.lower()))
        score += len(q_words & vocab)
        if score > 0 or a.required:
            scored.append((score, a))
    scored.sort(key=lambda p: p[0], reverse=True)
    chosen = [a for _s, a in scored[:_ATTR_CAP]]
    if not chosen:
        chosen = attrs[: min(20, len(attrs))]

    bundles: list[AttrCandidateBundle] = []
    for a in chosen:
        values: list[ValueCandidate] = []
        ranked_opts = _rank_value_candidates_by_relevance(a.options, q_words, question_lower)
        for i, o in enumerate(ranked_opts[:_VALUE_CAP]):
            values.append(ValueCandidate(
                index=i, item_value=o.item_value, display_name=o.display_name,
            ))
        bundles.append(AttrCandidateBundle(attr=a, values=values))
    return bundles


def _format_candidates_for_prompt(bundles: list[AttrCandidateBundle],
                                  session: CpqSession) -> str:
    lines: list[str] = []
    for b in bundles:
        a = b.attr
        current = (
            session.filled_multi.get(a.variable_name)
            or session.filled.get(a.variable_name)
        )
        if b.values:
            val_lines = "; ".join(
                f"[{v.index}] {v.display_name}" for v in b.values
            )
        else:
            val_lines = "(free-text / no menu — value_ref must be null)"
        lines.append(
            f"- variable_name={a.variable_name!r} label={a.display_label!r} "
            f"type={a.select_type} current={current!r}\n"
            f"  VALUE CANDIDATES: {val_lines}"
        )
    return "\n".join(lines)


def resolve_value_from_ref(
    result: GatewayIntentResult,
    bundles: list[AttrCandidateBundle],
) -> tuple[str | None, str | None]:
    """Map value_ref → (display_name, item_value) via OUR candidate lists.

    The model never supplies item_value text; we look it up by index.
    """
    if result.variable_name is None or result.value_ref is None:
        return None, None
    for b in bundles:
        if b.attr.variable_name != result.variable_name:
            continue
        if 0 <= result.value_ref < len(b.values):
            v = b.values[result.value_ref]
            return v.display_name, v.item_value
        return None, None
    return None, None
