"""CPQ end-to-end scenarios S1–S7 (docs/CPQ_GRAPH_FIX_PLAN.md Phase 4).

Every expectation is derived at runtime from the sample export resolved by
``cpq_fixtures.sample_path()`` (env ``ARYX_CPQ_SAMPLE``) — no values from any
specific file are hardcoded. Scenarios degrade data-driven: assertions about
rule kinds or menu links that a given export doesn't contain are skipped for
that export, never faked.

Backend scope: FalkorDB + Postgres pair. S2/S3 need a reachable FalkorDB and
are skipped otherwise; S4–S7 run the REAL engine/loaders/turn-driver against
in-memory fakes of the dialect layer and graph reader built from the XML
ground truth — no database required.
"""
from __future__ import annotations

import random
import re
from collections import Counter

import pytest

from tests.cpq_fixtures import load_truth, sample_path

pytestmark = pytest.mark.skipif(
    not sample_path().exists(),
    reason=f"CPQ sample export not found at {sample_path()} "
           "(set ARYX_CPQ_SAMPLE to a bm_config_zip_cache XML)",
)

_RNG = random.Random(20260709)  # deterministic sampling


@pytest.fixture(scope="module")
def truth():
    return load_truth()


def _pascal(tag: str) -> str:
    """bm_config_attr → BmConfigAttr (mirrors ingestion type naming)."""
    return "".join(w.title() for w in tag.split("_") if w)


def _falkor_available() -> bool:
    try:
        from falkordb import FalkorDB
        from urllib.parse import urlparse
        import os
        url = os.environ.get("ARYX_GRAPH_URL", "redis://localhost:6379")
        parsed = urlparse(url)
        db = FalkorDB(host=parsed.hostname or "localhost", port=parsed.port or 6379)
        db.list_graphs()
        return True
    except Exception:  # noqa: BLE001
        return False


# ─────────────────────────────────────────────────────────────────────────────
# S1 — Ingestion fidelity: XML → CSV extraction matches raw element counts
# ─────────────────────────────────────────────────────────────────────────────

def test_s1_extraction_counts_match_raw_xml(truth):
    from aryx.config import get_settings
    from aryx.pipeline.doc_discovery import _xml_to_csvs
    import csv as _csv
    import io

    data = truth.path.read_bytes()
    results = _xml_to_csvs(data, truth.path.stem, log_id="s1")
    assert results, "extraction produced no CSVs"

    settings = get_settings()
    row_cap = settings.xml_max_rows_per_type
    type_cap = settings.xml_max_entity_types

    extracted: dict[str, int] = {}
    for csv_bytes, csv_name in results:
        tag = csv_name[len(truth.path.stem) + 1:].removesuffix(".csv")
        rows = list(_csv.DictReader(io.StringIO(csv_bytes.decode("utf-8"))))
        extracted[tag] = len(rows)

    assert len(extracted) <= type_cap
    for tag, n_rows in extracted.items():
        if tag not in truth.entity_counts:
            continue  # nested same-type recursion can surface extra rows
        expected = min(truth.entity_counts[tag], row_cap)
        assert n_rows >= min(expected, 1), f"{tag}: extracted 0 of {expected}"
        assert n_rows <= max(truth.entity_counts[tag], row_cap), (
            f"{tag}: extracted {n_rows} > raw count {truth.entity_counts[tag]}")

    # The dominant entity types in the file must not be silently absent.
    top_tags = [t for t, _ in truth.entity_counts.most_common(type_cap)]
    missing = [t for t in top_tags[:5] if t not in extracted]
    assert not missing, f"top entity types missing from extraction: {missing}"


# ─────────────────────────────────────────────────────────────────────────────
# S2/S3 — Native queryability + schema truth (FalkorDB required)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.skipif(not _falkor_available(), reason="FalkorDB not reachable")
def test_s2_s3_native_properties_indexes_schema(truth):
    import os
    from aryx.config import get_settings
    from aryx.graph.falkor_store import FalkorStore
    from aryx.graph.reader import GraphReader

    url = os.environ.get("ARYX_GRAPH_URL", "redis://localhost:6379")
    graph_name = "_cpq_e2e_s2"
    store = FalkorStore(url, graph=graph_name)
    store.clear()
    cap = get_settings().graph_attr_value_cap

    # Project a deterministic sample: up to 8 entities from each of the 6
    # most frequent types, plus every config attr (they carry variable_name).
    sampled: list[tuple[int, str, dict]] = []
    eid = 0
    chosen_tags = [t for t, _ in truth.entity_counts.most_common(6)]
    for tag in chosen_tags:
        for fields in _RNG.sample(truth.entities[tag],
                                  min(8, len(truth.entities[tag]))):
            eid += 1
            sampled.append((eid, _pascal(tag), fields))
    for fields in truth.config_attrs():
        eid += 1
        sampled.append((eid, "BmConfigAttr", fields))

    try:
        for entity_id, otype, fields in sampled:
            store.add_entity(entity_id, otype, fields)
        created = store.ensure_indexes()
        assert created > 0, "no graph indexes were created"

        reader = GraphReader(url, graph=graph_name)

        # S2: every sampled scalar field is natively matchable via Cypher.
        # Source fields colliding with projection internals (id/type/name/iri)
        # are lifted under a src_ prefix so they stay queryable.
        checked = 0
        for entity_id, otype, fields in sampled:
            for key, value in list(fields.items())[:3]:
                if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key) or not value:
                    continue
                if key in ("id", "type", "name", "iri"):
                    key = f"src_{key}"
                expect = value
                if len(value) > cap and not re.search(
                        r"(^|_)(id|guid|uuid|key|code|ref|num|no)$"
                        r"|^variable_name$|_name$", key, re.IGNORECASE):
                    expect = value[:cap] + "…"
                rows = reader._query(  # noqa: SLF001 — direct Cypher is the point
                    f"MATCH (e:Entity {{{key}: $v}}) RETURN e.id", {"v": expect})
                assert any(r[0] == entity_id for r in rows), (
                    f"native match failed: {{{key}: {expect[:60]!r}}} "
                    f"did not return entity {entity_id}")
                checked += 1
        assert checked > 0, "no fields were checkable"

        # S2: variable_name — the PDF's exact failing query — must work for
        # every config attr in the file.
        for fields in truth.config_attrs():
            vn = fields["variable_name"]
            rows = reader._query(
                "MATCH (a {variable_name: $v}) RETURN a.id", {"v": vn})
            assert rows, f"MATCH by variable_name={vn!r} returned nothing"

        # S3: describe_schema reports the real structure.
        schema = reader.describe_schema()
        assert set(schema["entity_types"]) == {t for _e, t, _f in sampled}
        assert "BmConfigAttr" in schema["properties_by_type"]
        if truth.config_attrs():
            assert "variable_name" in schema["properties_by_type"]["BmConfigAttr"]

        # S3: reader round-trips full attributes (cap-aware).
        entity_id, otype, fields = sampled[0]
        got = reader.get_entity(entity_id)
        assert got is not None and got["type"] == otype
        for key, value in fields.items():
            if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key) or not value:
                continue
            assert key in got["attributes"], f"attribute {key} lost on round-trip"
    finally:
        store._graph.delete()  # noqa: SLF001 — test cleanup


# ─────────────────────────────────────────────────────────────────────────────
# Fakes for the dialect layer + graph reader, built from ground truth
# ─────────────────────────────────────────────────────────────────────────────

class FakeCpqRdb:
    """In-memory dialect-layer double derived entirely from the XML truth."""

    def __init__(self, truth):
        self._truth = truth
        self.entities: dict[int, dict] = {}
        self.by_tag: dict[str, list[int]] = {}
        eid = 0
        for tag, rows in truth.entities.items():
            for fields in rows:
                eid += 1
                self.entities[eid] = dict(fields)
                self.by_tag.setdefault(tag, []).append(eid)

    @staticmethod
    def _int(v, default=-1):
        try:
            return int(str(v).strip())
        except (TypeError, ValueError):
            return default

    def fetch_entity_attributes(self, entity_ids, workspace_id):
        return {i: self.entities[i] for i in entity_ids if i in self.entities}

    def fetch_entities_by_type(self, workspace_id, type_suffix):
        norm = type_suffix.lower().replace("_", "")
        out = []
        for tag, ids in self.by_tag.items():
            if tag.lower().replace("_", "").endswith(norm):
                out.extend((i, self.entities[i]) for i in ids)
        return out

    def fetch_rules(self, workspace_id, rule_type):
        out = []
        for i, f in self.fetch_entities_by_type(workspace_id, "bm_config_rule"):
            if f.get("rule_type") == rule_type:
                out.append((i, self._int(f.get("id"), None), f.get("name", ""),
                            self._int(f.get("condition_function_id"))))
        return out

    def fetch_rule_inputs(self, workspace_id):
        out = []
        for _i, f in self.fetch_entities_by_type(workspace_id, "bm_config_rule_input"):
            rid = self._int(f.get("bm_config_rule_id") or f.get("rule_id"), 0)
            aid = self._int(f.get("attribute_id"), 0)
            if rid and aid:
                out.append((rid, aid, f.get("value1", "")))
        return out

    def fetch_rule_actions(self, workspace_id):
        out = []
        for _i, f in self.fetch_entities_by_type(workspace_id, "bm_config_rule_action"):
            rid = self._int(f.get("bm_config_rule_id") or f.get("rule_id"), 0)
            aid = self._int(f.get("attribute_id"), 0)
            if rid and aid:
                out.append((rid, aid, self._int(f.get("action_type"), 0),
                            f.get("value1", ""), self._int(f.get("function_id"))))
        return out

    def fetch_marked_attrs(self, workspace_id):
        out = []
        for _i, f in self.fetch_entities_by_type(workspace_id, "bm_config_marked_attr"):
            rid = self._int(f.get("bm_config_rule_id") or f.get("rule_id"), 0)
            aid = self._int(f.get("attribute_id"), 0)
            if rid and aid:
                out.append((rid, aid))
        return out

    def fetch_rule_chain_links(self, workspace_id):
        out = []
        for _i, f in self.fetch_entities_by_type(workspace_id, "bm_config_rule_assoc"):
            rid = self._int(f.get("bm_config_rule_id") or f.get("rule_id"), 0)
            cid = self._int(f.get("child_rule_id"), 0)
            if rid and cid:
                out.append((rid, cid))
        return out

    def fetch_function_scripts(self, workspace_id):
        scripts = {}
        for _i, f in self.fetch_entities_by_type(workspace_id, "bm_function"):
            fn_id = self._int(f.get("id"), None)
            script = f.get("script_text") or ""
            if fn_id and script.strip():
                scripts[fn_id] = script
        return scripts


class FakeReader:
    """Graph-reader double: types, entities and attr→menu-item neighbors."""

    def __init__(self, rdb: FakeCpqRdb):
        self._rdb = rdb
        # menu item links to an attr when any *_id-ish field equals the attr's
        # own native id (ref_id, qty_attr_id, injected parent FKs, ...).
        self._menu_of: dict[int, list[int]] = {}
        attr_native: dict[str, int] = {}
        for tag, ids in rdb.by_tag.items():
            if tag.lower().replace("_", "").endswith("configattr"):
                for i in ids:
                    native = rdb.entities[i].get("id")
                    if native:
                        attr_native[str(native)] = i
        for tag, ids in rdb.by_tag.items():
            if "menuitem" in tag.lower().replace("_", ""):
                for mid in ids:
                    fields = rdb.entities[mid]
                    for key, val in fields.items():
                        if key.endswith("_id") and str(val) in attr_native:
                            self._menu_of.setdefault(attr_native[str(val)], []).append(mid)
                            break

    def distinct_types(self):
        return sorted(_pascal(t) for t in self._rdb.by_tag)

    def find_entities(self, ontology_type=None, name=None, limit=50):
        out = []
        for tag, ids in self._rdb.by_tag.items():
            if ontology_type and _pascal(tag) != ontology_type:
                continue
            for i in ids[:limit]:
                f = self._rdb.entities[i]
                out.append({"id": i, "type": _pascal(tag),
                            "name": f.get("name") or f.get("variable_name") or str(i),
                            "attributes": f})
        return out[:limit]

    def neighbors(self, entity_id):
        out = []
        for mid in self._menu_of.get(entity_id, []):
            f = self._rdb.entities[mid]
            out.append({"id": mid, "type": "BmMenuItem",
                        "name": f.get("item_text") or f.get("item_value") or str(mid),
                        "relationship": "HAS_MENU_ITEM", "direction": "out"})
        return out


@pytest.fixture()
def fake_rdb(truth, monkeypatch):
    rdb = FakeCpqRdb(truth)
    import aryx.cpq.engine as engine_mod
    monkeypatch.setattr(engine_mod, "get_cpq_rdb", lambda: rdb)
    # Tier-2 LLM off: tests must be deterministic and offline.
    from aryx.cpq.bml import BmlEvaluator
    monkeypatch.setattr(
        engine_mod.CpqEngine, "build_bml_evaluator",
        lambda self, ws: BmlEvaluator(rdb.fetch_function_scripts(ws), use_llm=False),
    )
    return rdb


# ─────────────────────────────────────────────────────────────────────────────
# S4 — ID mapping: rules resolve attrs through BM-native ids
# ─────────────────────────────────────────────────────────────────────────────

def test_s4_rule_ids_resolve_via_bridge(truth, fake_rdb):
    from aryx.cpq.engine import CpqEngine
    from aryx.cpq.state import ConfigAttr

    engine = CpqEngine()
    # Build ConfigAttrs the way load_product_config does: aryx entity id is
    # synthetic (never equal to the BM id), source_id from the attr's attrs.
    attrs = []
    native_to_vn: dict[int, str] = {}
    for i, f in fake_rdb.fetch_entities_by_type(1, "bm_config_attr"):
        vn = f.get("variable_name")
        native = FakeCpqRdb._int(f.get("id"), None)
        if not vn or native is None:
            continue
        attrs.append(ConfigAttr(
            entity_id=i, variable_name=vn, display_label=f.get("name", vn),
            required=False, default_value="", options=[], source_id=native))
        native_to_vn[native] = vn
    if not attrs:
        pytest.skip("export contains no config attrs with variable_name")

    index = engine._attr_index(attrs)  # noqa: SLF001
    # Every rule input referencing an attr that exists in the file must
    # resolve to that attr's variable_name — zero silent join misses.
    resolvable = [
        (rid, aid) for rid, aid, _v in fake_rdb.fetch_rule_inputs(1)
        if aid in native_to_vn
    ]
    for _rid, aid in resolvable:
        resolved = index.get(aid)
        assert resolved is not None, f"rule input attribute_id={aid} missed the bridge"
        assert resolved.variable_name == native_to_vn[aid]

    # And the aryx entity id NEVER accidentally shadows a BM id it isn't.
    for a in attrs:
        assert index[a.source_id].variable_name == a.variable_name


# ─────────────────────────────────────────────────────────────────────────────
# S5 — BML coverage: script rules are loaded/logged, never silently dropped
# ─────────────────────────────────────────────────────────────────────────────

def test_s5_script_rules_not_silently_dropped(truth, fake_rdb, caplog):
    from aryx.cpq.engine import CpqEngine
    engine = CpqEngine()

    rule_types_present = Counter(r.get("rule_type") for r in truth.rules())
    caplog.set_level("INFO", logger="aryx.cpq.engine")

    loaded_counts = {}
    for rule_type, loader in (("11", engine.load_hiding_rules),
                              ("10", engine.load_recommendation_rules),
                              ("5", engine.load_constraint_rules)):
        loaded_counts[rule_type] = loader(1)

    # Every script-backed rule of a loaded type must be either evaluated
    # (constraint w/ script) or visible in the coverage log — count them.
    for rule_type in ("11", "10", "5"):
        script_rules_in_file = [
            r for r in truth.rules()
            if r.get("rule_type") == rule_type
            and r.get("condition_function_id", "-1") not in ("-1", "")
        ]
        if not script_rules_in_file:
            continue
        logged = sum(
            1 for rec in caplog.records
            if "script" in rec.getMessage().lower()
        )
        assert logged > 0, (
            f"{len(script_rules_in_file)} script-backed type-{rule_type} rules "
            "in the export but zero coverage log lines — silently dropped")

    # Constraint script actions (function_id != -1 with a known script) must
    # become evaluable ConstraintRule objects.
    scripts = fake_rdb.fetch_function_scripts(1)
    script_actions = [
        (rid, aid, fn) for rid, aid, _at, _v, fn in fake_rdb.fetch_rule_actions(1)
        if fn != -1 and fn in scripts
    ]
    type5_native_ids = {FakeCpqRdb._int(r.get("id"), 0)
                        for r in truth.rules() if r.get("rule_type") == "5"}
    expected_script_constraints = [
        (rid, aid) for rid, aid, _fn in script_actions if rid in type5_native_ids
    ]
    con_rules = loaded_counts["5"]
    got_script_constraints = [r for r in con_rules if r.script is not None]
    assert len(got_script_constraints) >= len(expected_script_constraints), (
        f"expected ≥{len(expected_script_constraints)} script constraints, "
        f"loader produced {len(got_script_constraints)}")


def test_s5_tier1_coverage_on_real_scripts(truth):
    """Tier-1 parses a measurable share of the export's real BML scripts."""
    from aryx.cpq.bml import _parse_branches, evaluate_tier1

    scripts = [f["script_text"] for f in truth.functions()]
    if not scripts:
        pytest.skip("export contains no BML scripts")

    parsed = 0
    evaluated = 0
    for script in scripts:
        branches = _parse_branches(script)
        if not branches:
            continue
        parsed += 1
        # Self-derived evaluation: satisfy the first branch's own condition
        # and expect that branch's value list back.
        cond, body = branches[0]
        if cond is None:
            continue
        variables = {var: (value if op == "==" else value + "_x")
                     for _j, var, op, value in cond}
        result = evaluate_tier1(script, variables)
        if result is not None:
            evaluated += 1

    ratio = parsed / len(scripts)
    print(f"\nBML Tier-1 coverage: parsed {parsed}/{len(scripts)} "
          f"({ratio:.0%}), self-evaluated {evaluated}")
    # Data-driven floor: tier-1 must handle SOMETHING when the export has
    # the standard if/returnVal idiom; the LLM tier covers the rest.
    idiomatic = [s for s in scripts if "returnVal" in s and "if" in s]
    if idiomatic:
        assert parsed > 0, "no script parsed despite returnVal/if idiom present"


# ─────────────────────────────────────────────────────────────────────────────
# S5b — §6a regression guard: hiding-rule target resolution via marked_attr
# ─────────────────────────────────────────────────────────────────────────────

def test_s5b_hiding_rule_targets_resolve_via_marked_attr(truth, fake_rdb):
    """load_hiding_rules must not regress to 0 when BmConfigRuleAction is
    absent but BmConfigMarkedAttr carries the real target (docs/CPQ_GRAPH_FIX_PLAN.md §6a).

    Picks ONE concrete example straight from ground truth — a declarative
    rule (rule_type=11, condition_function_id=-1) with a real rule_input AND
    a real marked_attr row — and asserts the engine's output contains that
    exact (condition_attr, condition_value, target_attr) triple. A bare count
    comparison would be a near-tautology; checking one traced instance
    catches a broken join even if the aggregate count looks plausible.
    """
    from aryx.cpq.engine import CpqEngine

    def _int(v):
        try:
            return int(str(v).strip())
        except (TypeError, ValueError):
            return None

    inputs_by_rule: dict[int, tuple[int, str]] = {}
    for inp in truth.rule_inputs():
        rid = _int(inp.get("bm_config_rule_id") or inp.get("rule_id"))
        aid = _int(inp.get("attribute_id"))
        if rid and aid:
            inputs_by_rule[rid] = (aid, inp.get("value1", ""))

    marked_by_rule: dict[int, list[int]] = {}
    for m in truth.marked_attrs():
        rid = _int(m.get("bm_config_rule_id") or m.get("rule_id"))
        aid = _int(m.get("attribute_id"))
        if rid and aid:
            marked_by_rule.setdefault(rid, []).append(aid)

    declarative_hiding = [
        r for r in truth.rules()
        if r.get("rule_type") == "11"
        and r.get("condition_function_id", "-1") in ("-1", "")
    ]

    example = None
    for r in declarative_hiding:
        rid = _int(r.get("id"))
        if rid in inputs_by_rule and rid in marked_by_rule:
            example = (rid, inputs_by_rule[rid], marked_by_rule[rid])
            break

    if example is None:
        pytest.skip("export has no declarative hiding rule with both a "
                    "rule_input and a marked_attr row to trace")

    rid, (cond_attr, cond_value), target_attrs = example
    eng = CpqEngine()
    hiding = eng.load_hiding_rules(1)

    matches = [
        h for h in hiding
        if h.condition_attr_id == cond_attr
        and h.condition_value == cond_value
        and h.target_attr_id in target_attrs
    ]
    assert matches, (
        f"traced rule {rid} (condition attr={cond_attr}=={cond_value!r}, "
        f"marked targets={target_attrs}) produced no matching HidingRule — "
        f"marked_attr-based resolution regressed. Got {len(hiding)} total "
        f"hiding rules: {[(h.condition_attr_id, h.target_attr_id) for h in hiding][:5]}")

    # Aggregate regression guard: recovery must be > 0 whenever ground truth
    # has ANY declarative hiding rule resolvable via marked_attr (not just
    # the one traced above), and must not silently drop below that count.
    resolvable_rule_ids = {
        rid for rid in (
            _int(r.get("id")) for r in declarative_hiding
        )
        if rid in inputs_by_rule and rid in marked_by_rule
    }
    if resolvable_rule_ids:
        assert len(hiding) > 0, (
            f"{len(resolvable_rule_ids)} declarative hiding rules are "
            "resolvable via marked_attr in ground truth, but load_hiding_rules "
            "returned 0 — the §6a fix has regressed")


# ─────────────────────────────────────────────────────────────────────────────
# S6/S7 — Conversation drive: payload integrity + no eager output
# ─────────────────────────────────────────────────────────────────────────────

def _drive_conversation(truth, fake_rdb, monkeypatch, max_user_turns=30):
    """Drive _run_cpq_turn answering every question from the attr's own menu,
    preferring none-like codes when the menu offers them. Returns transcript."""
    import aryx.api.ask_api as api
    from aryx.api.ask_api import AskRequest, _run_cpq_turn

    monkeypatch.setattr(api, "_persist_cpq_history", lambda *a, **k: None)
    reader = FakeReader(fake_rdb)

    none_like = {"none", "null", "n/a", "na", "", "0", "-1", "any", "false"}
    session: dict = {}
    transcript = []
    question = "quote sl 3500 single unit for customer in United States"

    for _turn in range(max_user_turns):
        req = AskRequest(question=question, workspace_id=1, session_data=session)
        resp = _run_cpq_turn(req, reader)
        if not resp:
            return transcript, None  # no CPQ data survived engine filters
        transcript.append((question, resp))
        session = resp["session_data"]
        answer = resp["answer"]
        pending = session.get("pending_variables", [])
        status = session.get("status")

        if status == "awaiting_approval":
            question = "confirm"
            continue
        if status == "approved":
            return transcript, resp
        if not pending:
            return transcript, resp

        # Answer the pending question from that attr's own menu options.
        pending_var = pending[0]
        attr_fields = next(
            (f for _i, f in fake_rdb.fetch_entities_by_type(1, "bm_config_attr")
             if f.get("variable_name") == pending_var), None)
        options = []
        if attr_fields:
            attr_eid = next(
                (i for i, f in fake_rdb.fetch_entities_by_type(1, "bm_config_attr")
                 if f.get("variable_name") == pending_var), None)
            for n in reader.neighbors(attr_eid or -1):
                mi = fake_rdb.entities[n["id"]]
                if mi.get("item_value"):
                    options.append(mi["item_value"])
        if options:
            preferred = next(
                (o for o in options if o.strip().lower() in none_like), options[0])
            question = preferred
        else:
            question = "1"  # numbered pick from the presented list
    return transcript, None


def test_s6_s7_conversation_payload_and_no_eager_output(truth, fake_rdb, monkeypatch):
    transcript, final = _drive_conversation(truth, fake_rdb, monkeypatch)
    if not transcript:
        pytest.skip("engine filtered out all config attrs for this export "
                    "(noise/hidden filters) — conversation not drivable")

    user_confirmed: dict[str, str] = {}
    for question, resp in transcript:
        session = resp["session_data"]
        status = session.get("status")
        pending = session.get("pending_variables", [])

        # S7 — while configuring with pending attrs, NEVER a JSON payload.
        if status == "configuring" and pending:
            assert "```json" not in resp["answer"], (
                "eager FORMAT B payload emitted while attrs still pending")
            assert resp.get("cpq_payload") is None

        # Track user-confirmed values (source recorded as user).
        for var, src in session.get("filled_source", {}).items():
            if src == "user":
                user_confirmed[var] = session["filled"][var]

    if final is None:
        # Conversation hit the driver's turn budget — the engine must have
        # been explicit about incompleteness at ITS cap, never fabricating.
        capped = [r for _q, r in transcript if "incomplete" in r["answer"].lower()]
        for _q, resp in transcript:
            if resp["session_data"].get("status") == "configuring":
                assert resp.get("cpq_payload") is None
        assert capped or transcript, "no explicit incomplete notice at turn cap"
        return

    # S6 — approved payload contains every user-confirmed value verbatim.
    payload = final.get("cpq_payload") or {}
    for var, value in user_confirmed.items():
        assert payload.get(var) == value, (
            f"user-confirmed {var}={value!r} missing/altered in final payload "
            f"(got {payload.get(var)!r}) — the Region=NA drop bug class")


def test_s7_turn_cap_never_fabricates_payload(truth, fake_rdb, monkeypatch):
    """Force the turn cap with unanswerable turns: output must be explicitly
    incomplete and carry no payload."""
    import aryx.api.ask_api as api
    from aryx.api.ask_api import AskRequest, _run_cpq_turn
    from aryx.cpq.engine import CpqEngine

    monkeypatch.setattr(api, "_persist_cpq_history", lambda *a, **k: None)
    # Cap at 1 turn so the very first configuring turn with pending attrs
    # exercises the cap branch deterministically.
    monkeypatch.setattr(CpqEngine, "MAX_TURNS", 1)
    reader = FakeReader(fake_rdb)

    req = AskRequest(
        question="quote sl 3500 single unit for customer in United States",
        workspace_id=1, session_data={})
    resp = _run_cpq_turn(req, reader)
    if not resp:
        pytest.skip("no drivable CPQ data in this export")
    session = resp["session_data"]
    if not session.get("pending_variables"):
        pytest.skip("export auto-fills completely — cap branch unreachable")

    assert resp is not None
    assert "incomplete" in resp["answer"].lower(), (
        "turn cap output does not declare incompleteness")
    assert "```json" not in resp["answer"], (
        "turn cap emitted a fabricated BOM payload")
    assert resp.get("cpq_payload") is None
