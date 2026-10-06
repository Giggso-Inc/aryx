"""script_text must fold onto its function even when CSV BML enrichment added query-table lists to it.

Dev runs with ARYX_CSV_BML_ENABLED=true: enrichment gives every SQL-bearing script node three list properties,
which used to make the whole tag a non-leaf, so the text landed as a separate ScriptText entity and the
BmFunction rows carried no script (WS 1126/1147/1150/1166).
"""
from __future__ import annotations

from collections import defaultdict

from aryx.cpq_ingestion.constants import RAW_PROP_TEXT
from aryx.cpq_ingestion.raw_graph.leaf_audit import find_unfolded_leaf_tags
from aryx.cpq_ingestion.raw_graph.models import RawEdge, RawGraphProjection, RawNode
from aryx.cpq_ingestion.raw_graph.structural_leaf import fold_structural_leaf_tags, is_structural_leaf_tag
from aryx.csv_bml_ingestion.bml_graph import QUERIES_KEY, QUERY_TABLES_KEY, TABLES_KEY, enrich_projection
from aryx.csv_bml_ingestion.stored_graph import StoredGraphLookup  # noqa: F401  (import check)

_SQL = "SELECT attr1, val1 FROM attrToPart WHERE model = $cpqModel AND region = 'US' ORDER BY attr1"


def _projection(scripts: list[str]) -> RawGraphProjection:
    """root > bm_function(n) > {name, script_text}"""
    nodes = [RawNode(id=1, tag="root", properties={})]
    edges: list[RawEdge] = []
    next_id = 2
    for i, body in enumerate(scripts):
        fn_id, name_id, text_id = next_id, next_id + 1, next_id + 2
        next_id += 3
        nodes += [
            RawNode(id=fn_id, tag="bm_function", properties={}),
            RawNode(id=name_id, tag="name", properties={RAW_PROP_TEXT: f"fn{i}"}),
            RawNode(id=text_id, tag="script_text", properties={RAW_PROP_TEXT: body}),
        ]
        edges += [RawEdge(source_id=1, target_id=fn_id, name="CONTAINS"),
                  RawEdge(source_id=fn_id, target_id=name_id, name="CONTAINS"),
                  RawEdge(source_id=fn_id, target_id=text_id, name="CONTAINS")]
    return RawGraphProjection(nodes=nodes, edges=edges)


def _by_tag(projection: RawGraphProjection) -> dict[str, list[RawNode]]:
    out: dict[str, list[RawNode]] = defaultdict(list)
    for n in projection.nodes:
        out[n.tag].append(n)
    return dict(out)


def test_enrichment_makes_script_text_carry_extra_properties():
    enriched = enrich_projection(_projection([_SQL, "return 1;"]))
    props = [set(n.properties) for n in enriched.nodes if n.tag == "script_text"]
    assert {RAW_PROP_TEXT, TABLES_KEY, QUERIES_KEY, QUERY_TABLES_KEY} in props


def test_one_enriched_script_among_plain_ones_still_classifies_as_leaf():
    """The old test was per tag: a single SQL-bearing node made all of them non-leaf."""
    enriched = enrich_projection(_projection([_SQL, "return 1;", "return 2;"]))
    parent_ids = {e.source_id for e in enriched.edges}
    assert is_structural_leaf_tag(_by_tag(enriched)["script_text"], parent_ids) is True


def test_a_real_attribute_still_blocks_the_fold_even_alongside_bml_lists():
    enriched = enrich_projection(_projection([_SQL]))
    node = next(n for n in enriched.nodes if n.tag == "script_text")
    node.properties["lang"] = "bml"
    assert is_structural_leaf_tag([node], parent_ids=set()) is False


def test_fold_puts_text_and_query_lists_on_the_function():
    enriched = enrich_projection(_projection([_SQL, "return 1;"]))
    folded = fold_structural_leaf_tags(enriched.edges, _by_tag(enriched))
    assert "script_text" not in folded
    fns = sorted((n for n in folded["bm_function"]), key=lambda n: n.id)
    assert fns[0].properties["script_text"] == _SQL
    assert fns[0].properties[TABLES_KEY] == ["attrtopart"]
    assert fns[0].properties[QUERIES_KEY] == [_SQL]
    assert fns[0].properties[QUERY_TABLES_KEY] == ["attrtopart"]
    assert fns[1].properties["script_text"] == "return 1;"
    assert TABLES_KEY not in fns[1].properties
    assert find_unfolded_leaf_tags(folded, enriched.edges) == {}


def test_fold_extends_lists_instead_of_nesting_when_a_function_has_two_scripts():
    sql2 = "SELECT item FROM decodeMatrix WHERE cpqModel = $cpqModel AND availableForUpgrade = 'X'"
    nodes = [RawNode(id=1, tag="bm_function", properties={}),
             RawNode(id=2, tag="script_text", properties={RAW_PROP_TEXT: _SQL}),
             RawNode(id=3, tag="script_text", properties={RAW_PROP_TEXT: sql2})]
    edges = [RawEdge(source_id=1, target_id=2, name="CONTAINS"), RawEdge(source_id=1, target_id=3, name="CONTAINS")]
    enriched = enrich_projection(RawGraphProjection(nodes=nodes, edges=edges))
    folded = fold_structural_leaf_tags(enriched.edges, _by_tag(enriched))
    fn = folded["bm_function"][0]
    assert fn.properties[TABLES_KEY] == ["attrtopart", "decodematrix"]
    assert len(fn.properties[QUERIES_KEY]) == len(fn.properties[QUERY_TABLES_KEY]) == 2
    assert fn.properties["script_text"] == [_SQL, sql2]


def test_fold_without_enrichment_is_unchanged():
    plain = _projection([_SQL])
    folded = fold_structural_leaf_tags(plain.edges, _by_tag(plain))
    fn = folded["bm_function"][0]
    assert fn.properties["script_text"] == _SQL
    assert TABLES_KEY not in fn.properties


# --- review follow-ups (N1 import guard, N2/N4 recorded script property) ------------------------------
def test_fold_records_the_tag_the_script_was_folded_under():
    from aryx.csv_bml_ingestion.bml_graph import SCRIPT_PROPS_KEY
    enriched = enrich_projection(_projection([_SQL, "return 1;"]))
    folded = fold_structural_leaf_tags(enriched.edges, _by_tag(enriched))
    fns = sorted(folded["bm_function"], key=lambda n: n.id)
    assert fns[0].properties[SCRIPT_PROPS_KEY] == ["script_text"]
    assert SCRIPT_PROPS_KEY not in fns[1].properties          # no query lists, nothing to name


def test_two_scripts_under_one_function_record_the_tag_once():
    from aryx.csv_bml_ingestion.bml_graph import SCRIPT_PROPS_KEY
    sql2 = "SELECT item FROM decodeMatrix WHERE cpqModel = $cpqModel AND availableForUpgrade = 'X'"
    nodes = [RawNode(id=1, tag="bm_function", properties={}),
             RawNode(id=2, tag="script_text", properties={RAW_PROP_TEXT: _SQL}),
             RawNode(id=3, tag="script_text", properties={RAW_PROP_TEXT: sql2})]
    edges = [RawEdge(source_id=1, target_id=2, name="CONTAINS"), RawEdge(source_id=1, target_id=3, name="CONTAINS")]
    enriched = enrich_projection(RawGraphProjection(nodes=nodes, edges=edges))
    folded = fold_structural_leaf_tags(enriched.edges, _by_tag(enriched))
    assert folded["bm_function"][0].properties[SCRIPT_PROPS_KEY] == ["script_text"]


def test_fold_still_works_when_the_bml_module_cannot_be_imported(monkeypatch):
    import builtins

    from aryx.cpq_ingestion.raw_graph import structural_leaf as sl
    real_import = builtins.__import__

    def failing(name, *a, **k):
        if name.startswith("aryx.csv_bml_ingestion"):
            raise ImportError("boom")
        return real_import(name, *a, **k)

    sl._BML_KEYS = None
    monkeypatch.setattr(builtins, "__import__", failing)
    try:
        plain = _projection([_SQL])
        folded = fold_structural_leaf_tags(plain.edges, _by_tag(plain))
    finally:
        monkeypatch.undo()
        sl._BML_KEYS = None
    assert folded["bm_function"][0].properties["script_text"] == _SQL


def test_a_failed_bml_import_is_not_cached_so_a_later_call_recovers(monkeypatch):
    import builtins

    from aryx.cpq_ingestion.raw_graph import structural_leaf as sl
    real_import = builtins.__import__

    def failing(name, *a, **k):
        if name.startswith("aryx.csv_bml_ingestion"):
            raise ImportError("boom")
        return real_import(name, *a, **k)

    sl._BML_KEYS = None
    with monkeypatch.context() as m:
        m.setattr(builtins, "__import__", failing)
        assert sl._carried_keys() == ()
    assert sl._carried_keys() == (TABLES_KEY, QUERIES_KEY, QUERY_TABLES_KEY)     # recovered, not stuck on ()
