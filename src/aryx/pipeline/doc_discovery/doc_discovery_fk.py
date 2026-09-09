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

logger = logging.getLogger(__name__)


def _detect_fk_links(plans: list[dict], log_id: str | None = None) -> list[dict]:
    """Detect FK-style joins between tabular plans by column name patterns.

    For each pair of plans (A, B), looks for columns in A whose names follow
    the pattern ``{TypeB}_id`` or ``{TypeB}_name`` (case-insensitive, singular
    or plural form) and builds a ``fk_links`` spec understood by
    ``run_pipeline``.  Only one edge spec is emitted per (source, target) pair.
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

    for i, plan_a in enumerate(plans):
        for j, plan_b in enumerate(plans):
            if i == j:
                continue
            pair_key = (plan_a["ontology_type"], plan_b["ontology_type"])
            if pair_key in seen:
                continue
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
            headers_b = plan_headers[j]
            id_col = next((c for c in headers_b if c.lower() in id_names), None)
            name_col = next((c for c in headers_b if c.lower() in name_names), None)
            mk0 = plan_b["match_keys"][0] if plan_b.get("match_keys") else None

            for col in plan_headers[i]:
                col_l = col.lower()
                target_attr: str | None = None
                if col_l.endswith("_id") and col_l[:-3] in tag_candidates:
                    target_attr = id_col or mk0
                elif col_l.endswith("_name") and col_l[:-5] in tag_candidates:
                    target_attr = name_col or mk0
                elif col_l in (type_b_l, singular_b) and (id_col or name_col):
                    target_attr = id_col or name_col
                if not target_attr:
                    continue
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
                break

    # ── Pass 2: code-keyed data (shared-suffix columns) ──────────────────────
    # Handles patterns that Pass 1 misses because they don't follow {type}_id.
    # Three rules, all columns scanned per pair (no break) so multiple relationship
    # columns each generate their own edge spec:
    #   Rule A — shared match key:  same column name in A and B
    #   Rule B — stem reference:    column in A contains B's match-key stem
    #   Rule C — suffix match:      both columns share the same key suffix
    seen2: set[tuple[str, str, str]] = set()  # (src_type, tgt_type, col_l)
    for i, plan_a in enumerate(plans):
        own_mk = (plan_a.get("match_keys") or [None])[0]
        own_mk_l = (own_mk or "").lower()
        for j, plan_b in enumerate(plans):
            if i == j:
                continue
            pair_key = (plan_a["ontology_type"], plan_b["ontology_type"])
            if pair_key in seen:
                continue
            mk_b = (plan_b.get("match_keys") or [None])[0]
            if not mk_b:
                continue
            mk_b_l = mk_b.lower()
            # Derive stem by stripping common key suffixes
            mk_stem = mk_b_l
            for sfx in ("_code", "_id", "_num", "_key", "_ref", "_no", "_cage"):
                if mk_b_l.endswith(sfx):
                    mk_stem = mk_b_l[: -len(sfx)]
                    break
            if len(mk_stem) < 3:
                continue

            for col in plan_headers[i]:
                col_l = col.lower()
                col2_key = (plan_a["ontology_type"], plan_b["ontology_type"], col_l)
                if col2_key in seen2:
                    continue
                src_upper = plan_a["ontology_type"].upper()
                # Rule A: column exactly equals B's match key and looks like a code
                # column — catches shared identifier columns across entity types.
                # Guards:
                #   own_mk_l — skip when both A and B are siblings sharing a parent FK
                #   _col_is_varying — skip single-value context fields
                if (col_l == mk_b_l and col_l != own_mk_l
                        and any(col_l.endswith(sfx) for sfx in key_suffixes)
                        and _is_varying(i, col)):
                    seen2.add(col2_key)
                    links.append({
                        "source_type": plan_a["ontology_type"],
                        "source_attr": col,
                        "target_type": plan_b["ontology_type"],
                        "target_attr": mk_b,
                        "name": f"{plan_b['ontology_type'].upper()}_HAS_{src_upper}",
                    })
                    logger.info("fk-pass2-ruleA log_id=%s: %s.%s -> %s.%s",
                                log_id, plan_a["ontology_type"], col, plan_b["ontology_type"], mk_b)
                    continue
                # Rule B: column contains B's match-key stem as a fragment AND has
                # a key suffix — catches hierarchical/reference column patterns
                if (mk_stem in col_l and col_l != mk_b_l
                        and any(col_l.endswith(sfx) for sfx in key_suffixes)
                        and _is_varying(i, col)
                        and _is_varying(j, mk_b)):
                    seen2.add(col2_key)
                    links.append({
                        "source_type": plan_a["ontology_type"],
                        "source_attr": col,
                        "target_type": plan_b["ontology_type"],
                        "target_attr": mk_b,
                        "name": f"{plan_b['ontology_type'].upper()}_HAS_{src_upper}",
                    })
                    logger.info("fk-pass2-ruleB log_id=%s: %s.%s -> %s.%s",
                                log_id, plan_a["ontology_type"], col, plan_b["ontology_type"], mk_b)
                    continue
                # Rule C: same key-suffix — both columns share a suffix like _CODE,
                # signalling a replacement / alternate-entity reference.
                # Target cardinality guard: if the join target column has only one
                # distinct value (e.g. company_id = constant) it cannot produce
                # meaningful per-row joins — only false cartesian-product edges.
                col_sfx = next((s for s in key_suffixes if col_l.endswith(s)), None)
                mk_sfx = next((s for s in key_suffixes if mk_b_l.endswith(s)), None)
                if (col_sfx and mk_sfx and col_sfx == mk_sfx
                        and col_l != mk_b_l and col_l != own_mk_l
                        and _is_varying(i, col)
                        and _is_varying(j, mk_b)):
                    seen2.add(col2_key)
                    links.append({
                        "source_type": plan_a["ontology_type"],
                        "source_attr": col,
                        "target_type": plan_b["ontology_type"],
                        "target_attr": mk_b,
                        "name": f"{plan_b['ontology_type'].upper()}_HAS_{src_upper}",
                    })
                    logger.info("fk-pass2-ruleC log_id=%s: %s.%s -> %s.%s",
                                log_id, plan_a["ontology_type"], col, plan_b["ontology_type"], mk_b)

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
        for i, plan_a in enumerate(plans):
            if i == j:
                continue
            pair_key = (plan_a["ontology_type"], plan_b["ontology_type"])
            if pair_key in seen or pair_key in seen3:
                continue
            # Find matching column (case-insensitive)
            actual_col = next(
                (c for c in plan_headers[i] if c.lower() == fk_col_l), None
            )
            if actual_col is None:
                continue
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

    logger.info("detect_fk_links log_id=%s plans=%d links_found=%d", log_id, len(plans), len(links))
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
        return []

    try:
        text = fn_plan["data"].decode("utf-8", "ignore")
        rows = list(csv.reader(io.StringIO(text)))
    except Exception:  # noqa: BLE001
        logger.warning("script-data-flow log_id=%s: could not parse %s CSV",
                        log_id, fn_plan["ontology_type"])
        return []
    if not rows:
        return []
    header = rows[0]
    script_col = next(
        (h for h in header if h.lower() in ("script_text", "script")), None,
    )
    if script_col is None:
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
                break

    return links
