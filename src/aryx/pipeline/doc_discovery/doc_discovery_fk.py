"""Column-name-driven FK detection between tabular ingest plans.

Split out of `pipeline/doc_discovery.py` (Raven Style Compliance Plan,
Phase 2a, 2026-09-03). `_detect_fk_links`/`_detect_script_data_flow_links`/
`_detect_fk_links_workspace` are directly whitebox-patched (`aryx.pipeline.
doc_discovery._detect_fk_links` etc.) across `test_doc_discovery.py`,
`test_ingest_confirmed_fk_detection_progress.py`, and `test_ingest_
confirmed_mentions_batching.py` — their only caller, `ingest_confirmed`,
stays in `doc_discovery.py` and imports them from here, so those patches
keep intercepting them unchanged.
"""
from __future__ import annotations

import csv
import io
import logging
import re

from aryx.pipeline.doc_discovery.doc_discovery_types import _id_like_names, _key_suffixes, _name_like_names, _singular
from aryx.raven_log import raven_log, would_log

logger = logging.getLogger(__name__)


def _detect_fk_links(plans: list[dict], log_id: str | None = None) -> list[dict]:
    """Detect FK-style joins between tabular plans by column name patterns.

    For each pair of plans (A, B), looks for columns in A whose names follow
    the pattern ``{TypeB}_id`` or ``{TypeB}_name`` (case-insensitive, singular
    or plural form) and builds a ``fk_links`` spec understood by
    ``run_pipeline``.  Only one edge spec is emitted per (source, target) pair.

    Complexity note (2026-09-23, docs/ingestion/SPARK_PARALLEL_MIGRATION_
    ANALYSIS_2026-09-23.md Phase 1 step 1): the original version of this
    function compared every plan against every other plan directly — O(N^2)
    in the number of plans, recomputing each target plan's tag/stem
    candidates and id/name/match-key columns from scratch on every one of
    those N^2 comparisons even though none of that depends on the source
    plan at all. At 32 plans that's ~1,000 pair-checks (negligible,
    confirmed <1% of a real ingest's wall-clock time). It does NOT stay
    negligible as file/entity-type count grows — 200 plans is ~40,000
    pair-checks, purely from this shape, nothing to do with row count.
    Threading does NOT fix this (this is pure CPU-bound Python — string/
    regex comparisons, no LLM/DB/network calls — so the GIL means more
    threads run no more of it concurrently); the actual fix is algorithmic.
    Pass 1 and Pass 3 below are rewritten to build a reverse index once
    (O(N)) and look candidate source columns up in it (O(1) avg) instead of
    re-scanning every other plan per plan. Pass 2's Rules A and C get the
    same treatment; Rule B (substring containment, not exact-stem
    equality) genuinely needs a different algorithm (e.g. Aho-Corasick
    multi-pattern matching) to be sub-quadratic and is NOT fixed here —
    left as-is, now only evaluated for pairs Rules A/C didn't already
    resolve, with computation that depends only on the target plan hoisted
    out of the per-source-plan loop (same win as Pass 1/3, just without the
    full complexity-class fix for that one rule).
    """
    if len(plans) < 2:
        return []

    key_suffixes = _key_suffixes()
    id_names = _id_like_names()
    name_names = _name_like_names()

    def _headers(data: bytes) -> list[str]:
        try:
            line = data.split(b"\n")[0].decode("utf-8", "ignore")
            return next(csv.reader(io.StringIO(line)))
        except Exception:  # noqa: BLE001
            return []

    def _col_is_varying(data: bytes, headers: list[str], col: str,
                        sample: int = 20) -> bool:
        """Return True if *col* has at least 2 distinct non-empty values in the
        first *sample* data rows.  Columns with a single constant value (e.g.
        company_id = "4118171" for every row) are organisational context fields,
        not FK references — linking on them creates cartesian-product false edges."""
        try:
            idx = headers.index(col)
            lines = data.split(b"\n")[1: sample + 1]
            seen_vals: set[str] = set()
            for line in lines:
                row = next(csv.reader(io.StringIO(line.decode("utf-8", "ignore"))), None)
                if row and idx < len(row):
                    v = row[idx].strip()
                    if v:
                        seen_vals.add(v)
                        if len(seen_vals) >= 2:
                            return True
        except Exception:  # noqa: BLE001
            pass
        return False  # 0 or 1 distinct value → constant field, skip

    plan_headers = [_headers(p["data"]) for p in plans]

    # Cardinality cache — _col_is_varying re-parses CSV bytes on every call.
    # Pass 2 runs O(N² × cols) iterations; caching avoids ≈ 24,000 re-parses
    # for a 20-plan XML ingest with 20 columns each.
    _varying_cache: dict[tuple[int, str], bool] = {}

    def _is_varying(plan_idx: int, col: str) -> bool:
        key = (plan_idx, col)
        if key not in _varying_cache:
            _varying_cache[key] = _col_is_varying(
                plans[plan_idx]["data"], plan_headers[plan_idx], col
            )
        return _varying_cache[key]

    seen: set[tuple[str, str]] = set()
    links: list[dict] = []

    # ── Pass 1: reverse-index build, once per plan (O(N)) ────────────────
    # Everything below depends only on plan_b (the target), never on
    # plan_a (the source) — hoisted out of the old per-pair loop so it
    # runs once per plan instead of once per (plan_a, plan_b) pair.
    stem_index: dict[str, list[int]] = {}       # stem -> [plan indices]
    exact_type_index: dict[str, list[int]] = {}  # type_l/singular -> [plan indices]
    id_col_of: list[str | None] = [None] * len(plans)
    name_col_of: list[str | None] = [None] * len(plans)
    mk0_of: list[str | None] = [None] * len(plans)

    for j, plan_b in enumerate(plans):
        type_b = plan_b["ontology_type"]
        type_b_l = type_b.lower()
        singular_b = _singular(type_b_l)
        # Candidate stems: every trailing-word-run of the de-camelCased
        # type name (not just the last word), in both snake_case and
        # joined form, singular and plural. Catches columns whose FK
        # prefix carries more context than the last word alone, e.g.
        # "attr_set_id" -> BmConfigAttrSet ("attr"+"set" suffix) or
        # "config_attr_id" -> BmConfigAttr ("config"+"attr" suffix) —
        # purely derived from the type name, no hardcoded column list.
        _words = re.findall(r'[A-Z][a-z0-9]*', type_b)
        tag_candidates: set[str] = {type_b_l, singular_b}
        for k in range(1, len(_words) + 1):
            suffix_words = _words[-k:]
            for form in ("_".join(w.lower() for w in suffix_words),
                         "".join(w.lower() for w in suffix_words)):
                tag_candidates.add(form)
                tag_candidates.add(_singular(form))
        for stem in tag_candidates:
            stem_index.setdefault(stem, []).append(j)
        exact_type_index.setdefault(type_b_l, []).append(j)
        exact_type_index.setdefault(singular_b, []).append(j)

        headers_b = plan_headers[j]
        id_col_of[j] = next((c for c in headers_b if c.lower() in id_names), None)
        name_col_of[j] = next((c for c in headers_b if c.lower() in name_names), None)
        mk0_of[j] = plan_b["match_keys"][0] if plan_b.get("match_keys") else None

    # ── Pass 1: source-plan scan, index lookups instead of re-scanning ───
    # For a FIXED source plan, the original scanned each target plan's
    # columns in header order and used the FIRST match for THAT target —
    # replicated here by scanning columns in order and, for each column,
    # resolving every not-yet-resolved target it stem-matches; results are
    # then emitted in target-plan order (not column-encounter order) so
    # output order matches the original exactly, not just output content.
    for i, plan_a in enumerate(plans):
        resolved: dict[int, tuple[str, str]] = {}   # j -> (source_col, target_attr)
        resolved_types: set[str] = set()             # target type strings already claimed this i
        for col in plan_headers[i]:
            col_l = col.lower()
            if col_l.endswith("_id"):
                rule, candidate_js = "id", stem_index.get(col_l[:-3], ())
            elif col_l.endswith("_name"):
                rule, candidate_js = "name", stem_index.get(col_l[:-5], ())
            else:
                rule, candidate_js = "exact", exact_type_index.get(col_l, ())
            for j in candidate_js:
                if j == i or j in resolved:
                    continue
                type_b = plans[j]["ontology_type"]
                if type_b in resolved_types:
                    continue
                pair_key = (plan_a["ontology_type"], type_b)
                if pair_key in seen:
                    continue
                if rule == "id":
                    target_attr = id_col_of[j] or mk0_of[j]
                elif rule == "name":
                    target_attr = name_col_of[j] or mk0_of[j]
                else:
                    target_attr = id_col_of[j] or name_col_of[j]
                if not target_attr:
                    continue
                resolved[j] = (col, target_attr)
                resolved_types.add(type_b)

        for j in sorted(resolved):
            col, target_attr = resolved[j]
            type_b = plans[j]["ontology_type"]
            pair_key = (plan_a["ontology_type"], type_b)
            seen.add(pair_key)
            src_upper = plan_a["ontology_type"].upper()
            # Edge direction in link_by_attribute: target_type → source_type
            # (parent has-child semantics). Name reflects that direction.
            link = {
                "source_type": plan_a["ontology_type"],
                "source_attr": col,
                "target_type": type_b,
                "target_attr": target_attr,
                "name": f"{type_b.upper()}_HAS_{src_upper}",
            }
            links.append(link)
            logger.info("fk-pass1 log_id=%s: %s.%s -> %s.%s (%s)",
                        log_id, plan_a["ontology_type"], col, type_b, target_attr, link["name"])
            if would_log("DEBUG"):
                raven_log("DEBUG", "P4", "ingest.fk.link pass1 column-name link added",
                          context={"log_id": log_id, "rule": "pass1", "source_type": plan_a["ontology_type"], "source_attr": col,
                                   "target_type": type_b, "target_attr": target_attr, "decision": "link",
                                   "reason_code": "PASS1"})

    # ── Pass 2: code-keyed data (shared-suffix columns) ──────────────────────
    # Handles patterns that Pass 1 misses because they don't follow {type}_id.
    # Three rules, all columns scanned per pair (no break) so multiple relationship
    # columns each generate their own edge spec:
    #   Rule A — shared match key:  same column name in A and B
    #   Rule B — stem reference:    column in A contains B's match-key stem
    #   Rule C — suffix match:      both columns share the same key suffix
    #
    # Rules A and C match on an EXACT string (the whole match-key value, or
    # its suffix) — both indexable in O(N), same technique as Pass 1/3
    # above. Rule B matches on SUBSTRING CONTAINMENT (B's match-key stem
    # appearing anywhere inside A's column name) — a fundamentally
    # different search problem that a simple exact-value index can't
    # answer; making Rule B itself sub-quadratic needs a multi-pattern
    # substring search structure (e.g. Aho-Corasick), not attempted here.
    # Splitting A/B/C into three separate top-level passes (each still
    # gated by the same `seen2` dedup, in the same A-then-B-then-C
    # priority the original's per-column `continue` chain enforced) removes
    # A's and C's O(N^2) redundant work entirely, and removes the
    # per-(i,j) mk_b/mk_stem recomputation from Rule B's still-quadratic
    # loop (hoisted below, computed once per plan instead of once per
    # pair) — same net effect as Pass 1/3's fix for two of the three
    # rules, real but smaller constant-factor relief for the third.
    seen2: set[tuple[str, str, str]] = set()  # (src_type, tgt_type, col_l)

    mk_b_of: list[str | None] = [None] * len(plans)
    mk_stem_of: list[str] = [""] * len(plans)
    mk_b_index: dict[str, list[int]] = {}
    suffix_index: dict[str, list[int]] = {}
    for j in range(len(plans)):
        mk_b = (plans[j].get("match_keys") or [None])[0]
        if not mk_b:
            continue
        mk_b_l = mk_b.lower()
        mk_stem = mk_b_l
        for sfx in ("_code", "_id", "_num", "_key", "_ref", "_no", "_cage"):
            if mk_b_l.endswith(sfx):
                mk_stem = mk_b_l[: -len(sfx)]
                break
        mk_b_of[j] = mk_b
        mk_stem_of[j] = mk_stem
        mk_b_index.setdefault(mk_b_l, []).append(j)
        mk_sfx = next((s for s in key_suffixes if mk_b_l.endswith(s)), None)
        if mk_sfx:
            suffix_index.setdefault(mk_sfx, []).append(j)

    # Rule A — exact match-key equality, index lookup.
    for i, plan_a in enumerate(plans):
        own_mk_l = ((plan_a.get("match_keys") or [None])[0] or "").lower()
        for col in plan_headers[i]:
            col_l = col.lower()
            if col_l == own_mk_l or not any(col_l.endswith(sfx) for sfx in key_suffixes):
                continue
            for j in mk_b_index.get(col_l, ()):
                if j == i:
                    continue
                plan_b = plans[j]
                pair_key = (plan_a["ontology_type"], plan_b["ontology_type"])
                if pair_key in seen:
                    continue
                col2_key = (plan_a["ontology_type"], plan_b["ontology_type"], col_l)
                if col2_key in seen2 or not _is_varying(i, col):
                    continue
                mk_b = mk_b_of[j]
                seen2.add(col2_key)
                links.append({
                    "source_type": plan_a["ontology_type"], "source_attr": col,
                    "target_type": plan_b["ontology_type"], "target_attr": mk_b,
                    "name": f"{plan_b['ontology_type'].upper()}_HAS_{plan_a['ontology_type'].upper()}",
                })
                logger.info("fk-pass2-ruleA log_id=%s: %s.%s -> %s.%s",
                            log_id, plan_a["ontology_type"], col, plan_b["ontology_type"], mk_b)
                if would_log("DEBUG"):
                    raven_log("DEBUG", "P4", "ingest.fk.link pass2-ruleA column-name link added",
                              context={"log_id": log_id, "rule": "pass2-ruleA", "source_type": plan_a["ontology_type"], "source_attr": col,
                                       "target_type": plan_b["ontology_type"], "target_attr": mk_b, "decision": "link",
                                       "reason_code": "PASS2_RULEA"})

    # Rule B — substring containment, still O(N^2 x cols) (see note above).
    for i, plan_a in enumerate(plans):
        own_mk_l = ((plan_a.get("match_keys") or [None])[0] or "").lower()
        for j, plan_b in enumerate(plans):
            if i == j:
                continue
            pair_key = (plan_a["ontology_type"], plan_b["ontology_type"])
            if pair_key in seen:
                continue
            mk_b = mk_b_of[j]
            mk_stem = mk_stem_of[j]
            if not mk_b or len(mk_stem) < 3:
                continue
            mk_b_l = mk_b.lower()
            for col in plan_headers[i]:
                col_l = col.lower()
                col2_key = (plan_a["ontology_type"], plan_b["ontology_type"], col_l)
                if col2_key in seen2:
                    continue
                if (mk_stem in col_l and col_l != mk_b_l
                        and any(col_l.endswith(sfx) for sfx in key_suffixes)
                        and _is_varying(i, col)
                        and _is_varying(j, mk_b)):
                    seen2.add(col2_key)
                    links.append({
                        "source_type": plan_a["ontology_type"], "source_attr": col,
                        "target_type": plan_b["ontology_type"], "target_attr": mk_b,
                        "name": f"{plan_b['ontology_type'].upper()}_HAS_{plan_a['ontology_type'].upper()}",
                    })
                    logger.info("fk-pass2-ruleB log_id=%s: %s.%s -> %s.%s",
                                log_id, plan_a["ontology_type"], col, plan_b["ontology_type"], mk_b)
                    if would_log("DEBUG"):
                        raven_log("DEBUG", "P4", "ingest.fk.link pass2-ruleB column-name link added",
                                  context={"log_id": log_id, "rule": "pass2-ruleB", "source_type": plan_a["ontology_type"], "source_attr": col,
                                           "target_type": plan_b["ontology_type"], "target_attr": mk_b, "decision": "link",
                                           "reason_code": "PASS2_RULEB"})

    # Rule C — shared key-suffix, index lookup. Target cardinality guard:
    # if the join target column has only one distinct value (e.g.
    # company_id = constant) it cannot produce meaningful per-row joins —
    # only false cartesian-product edges.
    for i, plan_a in enumerate(plans):
        own_mk_l = ((plan_a.get("match_keys") or [None])[0] or "").lower()
        for col in plan_headers[i]:
            col_l = col.lower()
            col_sfx = next((s for s in key_suffixes if col_l.endswith(s)), None)
            if not col_sfx:
                continue
            for j in suffix_index.get(col_sfx, ()):
                if j == i:
                    continue
                plan_b = plans[j]
                pair_key = (plan_a["ontology_type"], plan_b["ontology_type"])
                if pair_key in seen:
                    continue
                mk_b = mk_b_of[j]
                mk_b_l = mk_b.lower()
                col2_key = (plan_a["ontology_type"], plan_b["ontology_type"], col_l)
                if (col2_key in seen2 or col_l == mk_b_l or col_l == own_mk_l
                        or not _is_varying(i, col) or not _is_varying(j, mk_b)):
                    continue
                seen2.add(col2_key)
                links.append({
                    "source_type": plan_a["ontology_type"], "source_attr": col,
                    "target_type": plan_b["ontology_type"], "target_attr": mk_b,
                    "name": f"{plan_b['ontology_type'].upper()}_HAS_{plan_a['ontology_type'].upper()}",
                })
                logger.info("fk-pass2-ruleC log_id=%s: %s.%s -> %s.%s",
                            log_id, plan_a["ontology_type"], col, plan_b["ontology_type"], mk_b)
                if would_log("DEBUG"):
                    raven_log("DEBUG", "P4", "ingest.fk.link pass2-ruleC column-name link added",
                              context={"log_id": log_id, "rule": "pass2-ruleC", "source_type": plan_a["ontology_type"], "source_attr": col,
                                       "target_type": plan_b["ontology_type"], "target_attr": mk_b, "decision": "link",
                                       "reason_code": "PASS2_RULEC"})

    # ── Pass 3: XML element-type FK detection ─────────────────────────────────
    # _collect_tag injects {parent_tag}_id columns into child entity rows.
    # Pass 1 misses these because it compares against the full
    # PascalCase ontology type name; Pass 2 misses them when the match key is a
    # short generic like "id".  Here we read the raw XML element type from the
    # _element_type column of each plan and check whether any other plan's headers
    # contain {element_type}_id, which is exactly the parent FK pattern.

    def _first_value(data: bytes, headers: list[str], col: str) -> str | None:
        try:
            idx = headers.index(col)
            lines = data.split(b"\n")
            if len(lines) < 2:
                return None
            row = next(csv.reader(io.StringIO(lines[1].decode("utf-8", "ignore"))), None)
            if row and idx < len(row):
                return row[idx].strip() or None
        except Exception:  # noqa: BLE001
            return None
        return None

    plan_elem_types: list[str | None] = [
        _first_value(plans[k]["data"], plan_headers[k], "_element_type")
        if "_element_type" in plan_headers[k] else None
        for k in range(len(plans))
    ]

    # Reverse index: lowercased column name -> plan indices that have a
    # column with that exact name (dedup'd per plan, header order
    # preserved for the first-occurrence tie-break, same as the original
    # per-plan `next(...)` scan). Built once (O(N x cols)) instead of the
    # original's O(N^2 x cols) "for every element-type plan, rescan every
    # other plan's full header list looking for one exact name".
    col_index: dict[str, list[int]] = {}
    for i in range(len(plans)):
        seen_cols_i: set[str] = set()
        for c in plan_headers[i]:
            cl = c.lower()
            if cl in seen_cols_i:
                continue
            seen_cols_i.add(cl)
            col_index.setdefault(cl, []).append(i)

    seen3: set[tuple[str, str]] = set()
    for j, plan_b in enumerate(plans):
        elem_b = plan_elem_types[j]
        if not elem_b:
            continue
        fk_col_l = f"{elem_b}_id"
        headers_b = plan_headers[j]
        id_col_b = next((c for c in headers_b if c.lower() in id_names), None)
        mk0_b = plan_b["match_keys"][0] if plan_b.get("match_keys") else None
        target_attr = id_col_b or mk0_b
        if not target_attr:
            continue
        for i in col_index.get(fk_col_l, ()):
            if i == j:
                continue
            plan_a = plans[i]
            pair_key = (plan_a["ontology_type"], plan_b["ontology_type"])
            if pair_key in seen or pair_key in seen3:
                continue
            actual_col = next(c for c in plan_headers[i] if c.lower() == fk_col_l)
            seen3.add(pair_key)
            links.append({
                "source_type": plan_a["ontology_type"],
                "source_attr": actual_col,
                "target_type": plan_b["ontology_type"],
                "target_attr": target_attr,
                "name": f"{plan_b['ontology_type'].upper()}_HAS_{plan_a['ontology_type'].upper()}",
            })
            logger.debug(
                "fk-pass3 log_id=%s: %s.%s → %s.%s",
                log_id, plan_a["ontology_type"], actual_col,
                plan_b["ontology_type"], target_attr,
            )
            if would_log("DEBUG"):
                raven_log("DEBUG", "P4", "ingest.fk.link pass3 column-name link added",
                          context={"log_id": log_id, "rule": "pass3", "source_type": plan_a["ontology_type"], "source_attr": actual_col,
                                   "target_type": plan_b["ontology_type"], "target_attr": target_attr, "decision": "link",
                                   "reason_code": "PASS3"})

    logger.info("detect_fk_links log_id=%s plans=%d links_found=%d", log_id, len(plans), len(links))
    raven_log("DEBUG", "P4", "ingest.fk.detect column-name FK detection finished",
              context={"log_id": log_id, "plans": len(plans), "links_found": len(links),
                       "plan_types": [p.get("ontology_type") for p in plans][:50],
                       "selected_option": "links_found" if links else "no_links", "reason_code": "PASSES_1_TO_3"})
    return links


def _detect_script_data_flow_links(plans: list[dict], log_id: str | None = None) -> list[dict]:
    """Ingestion-time static analysis: recognize the array-iteration BML
    idiom in ``bm_function.script_text`` and materialize what it finds as
    permanent, queryable fk_link specs (docs/CPQ_BML_ARRAY_ITERATION_TIER_PLAN.md,
    Approach B).

    Sibling to ``_detect_fk_links`` — same {source_type, source_attr,
    target_type, target_attr, name} spec shape, consumed by the same
    ``link_by_attribute`` value-equality join, just a different discovery
    mechanism (script-text pattern recognition instead of column-name
    inference). Reuses ``aryx.cpq.bml.parse_array_iteration`` — the SAME
    recognizer a future runtime evaluator tier (Approach A) would use — as
    the single source of truth for this idiom; this pass never
    re-implements the pattern independently.

    Mechanism: ``link_by_attribute`` only knows how to join by VALUE
    equality between an existing column on each side — it has no way to
    join "a variable name parsed out of a free-text script column" without
    a real column to hold that value. So for each ``bm_function`` row
    whose script recognizes, three derived columns are appended to that
    plan's own CSV data (the parsed control/selector/quantity attribute
    names) and 3 fk_link specs point those new columns at the matching
    ``bm_config_attr`` rows' ``variable_name`` column — reusing the exact
    same materialization path ``_detect_fk_links``'s own output already
    goes through, no new pipeline plumbing required.

    Returns [] when no bm_function/bm_config_attr plan pair is present, or
    when no script in the bm_function plan recognizes as this idiom — a
    catalog with no array-iteration scripts is left completely unchanged.
    """
    from aryx.cpq.bml import parse_array_iteration

    fn_plan = next((p for p in plans if p["ontology_type"].endswith("BmFunction")), None)
    attr_plan = next((p for p in plans if p["ontology_type"].endswith("BmConfigAttr")), None)
    if fn_plan is None or attr_plan is None:
        raven_log("DEBUG", "P4", "ingest.fk.script_flow skipped, BML plans absent",
                  context={"log_id": log_id, "has_function_plan": fn_plan is not None,
                           "has_attr_plan": attr_plan is not None, "selected_option": "skip",
                           "reason_code": "BML_PLAN_PAIR_MISSING"})
        return []

    try:
        text = fn_plan["data"].decode("utf-8", "ignore")
        rows = list(csv.reader(io.StringIO(text)))
    except Exception:  # noqa: BLE001
        logger.warning("script-data-flow log_id=%s: could not parse %s CSV",
                        log_id, fn_plan["ontology_type"])
        raven_log("WARN", "P3", "ingest.fk.script_flow function CSV unparseable, analysis skipped",
                  error_code="ARYX_ING_SCRIPT_FLOW_SKIPPED",
                  context={"log_id": log_id, "triggering_error": "csv_parse", "recovery_selected": "skip_analysis",
                           "exit_condition": "skipped", "result": "degraded"})
        return []
    if not rows:
        raven_log("DEBUG", "P4", "ingest.fk.script_flow skipped, function CSV empty",
                  context={"log_id": log_id, "selected_option": "skip", "reason_code": "NO_ROWS"})
        return []
    header = rows[0]
    script_col = next(
        (h for h in header if h.lower() in ("script_text", "script")), None,
    )
    if script_col is None:
        raven_log("DEBUG", "P4", "ingest.fk.script_flow skipped, no script column",
                  context={"log_id": log_id, "header_column_names": header[:100], "selected_option": "skip",
                           "reason_code": "NO_SCRIPT_COLUMN"})
        return []
    script_idx = header.index(script_col)

    _CONTROL_COL, _SELECTOR_COL, _QTY_COL = (
        "_array_control_attr_ref", "_array_selector_attr_ref", "_array_qty_attr_ref",
    )
    rows_out = [header + [_CONTROL_COL, _SELECTOR_COL, _QTY_COL]]
    recognized = 0
    for row in rows[1:]:
        row = list(row) + [""] * max(0, len(header) - len(row))
        script = row[script_idx] if script_idx < len(row) else ""
        shape = parse_array_iteration(script)
        if shape:
            recognized += 1
            extra = [shape.control_attr, shape.selector_attr, shape.qty_attr or ""]
        else:
            extra = ["", "", ""]
        rows_out.append(row + extra)

    if not recognized:
        raven_log("DEBUG", "P4", "ingest.fk.script_flow no array-iteration scripts recognised",
                  context={"log_id": log_id, "scripts": len(rows) - 1, "recognized": 0, "selected_option": "skip",
                           "reason_code": "NO_RECOGNISED_SHAPES"})
        return []

    buf = io.StringIO()
    csv.writer(buf).writerows(rows_out)
    fn_plan["data"] = buf.getvalue().encode("utf-8")

    links = [
        {
            "source_type": fn_plan["ontology_type"], "source_attr": _CONTROL_COL,
            "target_type": attr_plan["ontology_type"], "target_attr": "variable_name",
            "name": "BMFUNCTION_ARRAY_ITERATES",
        },
        {
            "source_type": fn_plan["ontology_type"], "source_attr": _SELECTOR_COL,
            "target_type": attr_plan["ontology_type"], "target_attr": "variable_name",
            "name": "BMFUNCTION_READS_SELECTOR",
        },
        {
            "source_type": fn_plan["ontology_type"], "source_attr": _QTY_COL,
            "target_type": attr_plan["ontology_type"], "target_attr": "variable_name",
            "name": "BMFUNCTION_READS_QUANTITY",
        },
    ]
    logger.info(
        "script-data-flow log_id=%s: recognized %d/%d array-iteration script(s) in %s, "
        "emitting %d link spec(s)",
        log_id, recognized, len(rows) - 1, fn_plan["ontology_type"], len(links),
    )
    raven_log("DEBUG", "P4", "ingest.fk.script_flow array-iteration links emitted",
              context={"log_id": log_id, "scripts": len(rows) - 1, "recognized": recognized, "links": len(links)})
    return links


def _detect_fk_links_workspace(
    plan: dict, known_types: list[str], seen: set[tuple[str, str]] | None = None,
    job_id: str | None = None,
) -> list[dict]:
    """Detect FK links between one plan and workspace types already in OntologyStore.

    Fires even for single-file confirm jobs where _detect_fk_links returns [].
    For each column header matching {KnownType}_id or {KnownType}_name (case-
    insensitive, singular/plural), emits an FK spec for link_by_attribute.
    """
    seen = seen or set()
    links: list[dict] = []
    try:
        line = plan["data"].split(b"\n")[0].decode("utf-8", "ignore")
        headers = next(csv.reader(io.StringIO(line)), [])
    except Exception as exc:  # noqa: BLE001
        logger.warning("detect_fk_links_workspace job=%s file=%s header parse failed: %s",
                        job_id, plan.get("filename"), exc)
        raven_log("WARN", "P3", "ingest.fk.workspace header parse failed, workspace FK skipped",
                  error_code="ARYX_ING_WORKSPACE_FK_SKIPPED",
                  context={"job_id": job_id, "filename": plan.get("filename"), "triggering_error": type(exc).__name__,
                           "recovery_selected": "skip_workspace_fk", "exit_condition": "skipped", "result": "degraded"})
        return []

    src_type = plan.get("ontology_type", "")
    match_key = (plan.get("match_keys") or ["id"])[0]

    for known in known_types:
        if known == src_type:
            continue
        pair_key = (src_type, known)
        if pair_key in seen:
            continue
        known_l = known.lower()
        singular = known_l.rstrip("s")
        candidates = {
            f"{known_l}_id", f"{known_l}_name",
            f"{singular}_id", f"{singular}_name",
        }
        for col in headers:
            if col.lower() in candidates:
                seen.add(pair_key)
                links.append({
                    "source_type": src_type,
                    "source_attr": col,
                    "target_type": known,
                    "target_attr": match_key,
                    "name": f"{known.upper()}_HAS_{src_type.upper()}",
                })
                logger.info("fk-workspace job=%s: %s.%s -> %s.%s",
                            job_id, src_type, col, known, match_key)
                raven_log("DEBUG", "P4", "ingest.fk.workspace link added to existing type",
                          context={"job_id": job_id, "source_type": src_type, "source_attr": col,
                                   "target_type": known, "target_attr": match_key, "decision": "link",
                                   "reason_code": "KNOWN_TYPE_COLUMN_MATCH"})
                break

    raven_log("DEBUG", "P4", "ingest.fk.workspace finished",
              context={"job_id": job_id, "known_types": len(known_types), "links": len(links),
                       "already_seen_pairs": len(seen)})
    return links
