"""resolve_run() wiring: review-queue + survivorship-policy activation.

Verifies the previously-dead paths (StoreReviewSink, SurvivorshipPolicy) are
actually instantiated and used, and that DB/lookup failures degrade safely
rather than aborting the run.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from aryx.models import EntityMember, ResolutionRecord, ResolvedEntity
from aryx.resolve_entities import resolve_run


def _store_with_records(records: list[ResolutionRecord]) -> MagicMock:
    store = MagicMock()
    store.landed_records.return_value = records
    store.save.return_value = 0
    return store


def test_review_band_pair_reaches_adjudication_store() -> None:
    """A review-band pair should flow through StoreReviewSink into AdjudicationStore.enqueue."""
    records = [
        ResolutionRecord(record_id=1, text="Acme Corp", payload={"name": "Acme Corp"}),
        ResolutionRecord(record_id=2, text="Acme Corporation", payload={"name": "Acme Corporation"}),
    ]
    store = _store_with_records(records)
    broker = MagicMock()
    broker.embed.return_value = []  # force string-only scoring

    mock_adj_store = MagicMock()
    mock_ws_store = MagicMock()
    mock_ws_store.get_survivorship.return_value = {}

    with patch("aryx.resolve_entities.AdjudicationStore", return_value=mock_adj_store), \
         patch("aryx.resolve_entities.make_workspace_store", return_value=mock_ws_store), \
         patch("aryx.resolution.run.get_settings") as mock_settings:
        mock_settings.return_value.er_auto_merge = 1.0
        mock_settings.return_value.er_adjudicate = 1.0
        mock_settings.return_value.er_review = 0.0  # everything scoring > 0 goes to review band
        mock_settings.return_value.embed_batch_size = 50
        mock_settings.return_value.max_pairs_per_block = 500
        mock_settings.return_value.er_embed_workers = 8

        resolve_run(run_id=99, ontology_type="Company", key_attrs=["name"],
                   store=store, broker=broker, workspace_id=5)

    mock_adj_store.enqueue.assert_called()
    call_args = mock_adj_store.enqueue.call_args
    assert call_args[0][0] == 99  # run_id passed through to the sink


def test_survivorship_defaults_to_most_complete_when_unconfigured() -> None:
    """No workspace survivorship config -> policy defaults to most_complete."""
    store = _store_with_records([])
    broker = MagicMock()

    mock_ws_store = MagicMock()
    mock_ws_store.get_survivorship.return_value = {}

    with patch("aryx.resolve_entities.AdjudicationStore"), \
         patch("aryx.resolve_entities.make_workspace_store", return_value=mock_ws_store), \
         patch("aryx.resolve_entities.resolve") as mock_resolve:
        mock_resolve.return_value = []
        resolve_run(run_id=1, ontology_type="Company", key_attrs=["name"],
                   store=store, broker=broker, workspace_id=1)

    _, kwargs = mock_resolve.call_args
    assert kwargs["policy"].default_strategy == "most_complete"
    mock_ws_store.close.assert_called_once()


def test_review_sink_construction_failure_falls_back_to_none() -> None:
    """AdjudicationStore construction failing must not abort resolve_run."""
    store = _store_with_records([])
    broker = MagicMock()

    with patch("aryx.resolve_entities.AdjudicationStore", side_effect=RuntimeError("db down")), \
         patch("aryx.resolve_entities.make_workspace_store") as mock_make_ws, \
         patch("aryx.resolve_entities.resolve") as mock_resolve:
        mock_make_ws.return_value.get_survivorship.return_value = {}
        mock_resolve.return_value = []
        resolve_run(run_id=1, ontology_type="Company", key_attrs=["name"],
                   store=store, broker=broker, workspace_id=1)

    _, kwargs = mock_resolve.call_args
    assert kwargs["review"] is None


def test_survivorship_lookup_failure_falls_back_to_default() -> None:
    """Workspace-store lookup failing must not abort resolve_run — safe default used."""
    store = _store_with_records([])
    broker = MagicMock()

    with patch("aryx.resolve_entities.AdjudicationStore"), \
         patch("aryx.resolve_entities.make_workspace_store", side_effect=RuntimeError("db down")), \
         patch("aryx.resolve_entities.resolve") as mock_resolve:
        mock_resolve.return_value = []
        resolve_run(run_id=1, ontology_type="Company", key_attrs=["name"],
                   store=store, broker=broker, workspace_id=1)

    _, kwargs = mock_resolve.call_args
    assert kwargs["policy"].default_strategy == "most_complete"


# ── Chunked-resolver dispatch (large tabular sheets, e.g. 300K-row Data tabs) ─
# Regression coverage for a real incident: with no dispatch, ANY record count
# went through the in-memory resolve()'s O(block-size²) blocking/scoring pass
# unconditionally, and a 308,104-row sheet stalled ingestion for hours.

def _settings_stub(**overrides):
    base = dict(
        er_exact_id_match=True, er_chunk_threshold=100_000,
        er_min_key_selectivity=0.01, er_key_selectivity_sample_size=2000,
        er_force_exact_min_selectivity=1.0,
        id_like_column_names="id,uuid,guid,key",
        rdb_dsn="postgresql://x",
    )
    base.update(overrides)
    return MagicMock(**base)


def test_below_threshold_uses_in_memory_resolve() -> None:
    records = [ResolutionRecord(record_id=i, text=f"r{i}", payload={}) for i in range(5)]
    store = _store_with_records(records)
    broker = MagicMock()

    with patch("aryx.resolve_entities.AdjudicationStore"), \
         patch("aryx.resolve_entities.make_workspace_store") as mock_make_ws, \
         patch("aryx.resolve_entities.get_settings",
               return_value=_settings_stub(er_chunk_threshold=100)), \
         patch("aryx.resolve_entities.resolve") as mock_resolve, \
         patch("aryx.resolve_entities.resolve_chunked") as mock_chunked:
        mock_make_ws.return_value.get_survivorship.return_value = {}
        mock_resolve.return_value = []
        resolve_run(run_id=1, ontology_type="Company", key_attrs=["name"],
                   store=store, broker=broker, workspace_id=1)

    mock_resolve.assert_called_once()
    mock_chunked.assert_not_called()


def test_above_threshold_uses_chunked_resolver() -> None:
    records = [ResolutionRecord(record_id=i, text=f"r{i}", payload={}) for i in range(10)]
    store = _store_with_records(records)
    broker = MagicMock()

    with patch("aryx.resolve_entities.AdjudicationStore"), \
         patch("aryx.resolve_entities.make_workspace_store") as mock_make_ws, \
         patch("aryx.resolve_entities.get_settings",
               return_value=_settings_stub(er_chunk_threshold=5, er_exact_id_match=False)), \
         patch("aryx.resolve_entities.PgChunkBackend") as mock_backend_cls, \
         patch("aryx.resolve_entities.resolve") as mock_resolve, \
         patch("aryx.resolve_entities.resolve_chunked") as mock_chunked:
        mock_make_ws.return_value.get_survivorship.return_value = {}
        mock_chunked.return_value = iter([])
        resolve_run(run_id=1, ontology_type="Company", key_attrs=["name"],
                   store=store, broker=broker, workspace_id=1)

    mock_chunked.assert_called_once()
    mock_resolve.assert_not_called()
    mock_backend_cls.assert_called_once_with("postgresql://x", 1, ["name"])
    call_args = mock_chunked.call_args[0]
    assert call_args[0] == 1  # run_id
    assert call_args[2] == list(range(10))  # all_record_ids


def test_exact_ids_bypasses_chunking_regardless_of_size() -> None:
    """An id-keyed source resolves by exact equality — chunking has nothing
    to add there, so it must stay on the in-memory (exact_ids) path even
    when record count exceeds the chunk threshold."""
    records = [ResolutionRecord(record_id=i, text=f"r{i}", payload={}) for i in range(10)]
    store = _store_with_records(records)
    broker = MagicMock()

    with patch("aryx.resolve_entities.AdjudicationStore"), \
         patch("aryx.resolve_entities.make_workspace_store") as mock_make_ws, \
         patch("aryx.resolve_entities.get_settings",
               return_value=_settings_stub(er_chunk_threshold=5, er_exact_id_match=True)), \
         patch("aryx.resolve_entities.resolve") as mock_resolve, \
         patch("aryx.resolve_entities.resolve_chunked") as mock_chunked:
        mock_make_ws.return_value.get_survivorship.return_value = {}
        mock_resolve.return_value = []
        resolve_run(run_id=1, ontology_type="Company", key_attrs=["id"],
                   store=store, broker=broker, workspace_id=1)

    mock_resolve.assert_called_once()
    mock_chunked.assert_not_called()


# ── Key-selectivity guard ────────────────────────────────────────────────────
# Regression coverage for a real incident: a table whose match-key columns
# were each a single constant value across all 308,104 rows ran the FULL
# blocking/scoring pass (and separately, an unbatched per-cluster save)
# before reaching the exact same all-singleton outcome this guard reaches
# immediately, without ever running blocking at all.

def test_non_selective_key_skips_resolution_entirely() -> None:
    """All records share the exact same match text — zero identity signal.
    Resolution must be skipped and one entity materialized per record."""
    records = [ResolutionRecord(record_id=i, text="RP-00060001", payload={"n": i})
               for i in range(50)]
    store = _store_with_records(records)
    broker = MagicMock()

    with patch("aryx.resolve_entities.AdjudicationStore"), \
         patch("aryx.resolve_entities.make_workspace_store") as mock_make_ws, \
         patch("aryx.resolve_entities.get_settings",
               return_value=_settings_stub(er_min_key_selectivity=0.05, er_exact_id_match=False)), \
         patch("aryx.resolve_entities.resolve") as mock_resolve, \
         patch("aryx.resolve_entities.resolve_chunked") as mock_chunked:
        mock_make_ws.return_value.get_survivorship.return_value = {}
        store.save.return_value = 50
        resolve_run(run_id=1, ontology_type="Thing", key_attrs=["reporting_period_id"],
                   store=store, broker=broker, workspace_id=1)

    mock_resolve.assert_not_called()
    mock_chunked.assert_not_called()
    saved_results = store.save.call_args[0][0]
    assert len(saved_results) == 50  # one entity per record, no merging attempted
    for _entity, members in saved_results:
        assert len(members) == 1  # every cluster is a genuine singleton


def test_selective_key_does_not_trigger_the_guard() -> None:
    """Distinct match text per record -> selectivity 1.0 -> normal resolve()
    path runs, guard must not interfere."""
    records = [ResolutionRecord(record_id=i, text=f"unique-{i}", payload={})
               for i in range(50)]
    store = _store_with_records(records)
    broker = MagicMock()

    with patch("aryx.resolve_entities.AdjudicationStore"), \
         patch("aryx.resolve_entities.make_workspace_store") as mock_make_ws, \
         patch("aryx.resolve_entities.get_settings",
               return_value=_settings_stub(er_min_key_selectivity=0.01, er_exact_id_match=False)), \
         patch("aryx.resolve_entities.resolve") as mock_resolve, \
         patch("aryx.resolve_entities.resolve_chunked") as mock_chunked:
        mock_make_ws.return_value.get_survivorship.return_value = {}
        mock_resolve.return_value = []
        resolve_run(run_id=1, ontology_type="Thing", key_attrs=["name"],
                   store=store, broker=broker, workspace_id=1)

    mock_resolve.assert_called_once()
    mock_chunked.assert_not_called()


def test_exact_ids_bypasses_the_selectivity_guard_too() -> None:
    """exact_ids mode never runs pairwise scoring in the first place —
    the selectivity guard must not even be evaluated for it."""
    records = [ResolutionRecord(record_id=i, text="CONST", payload={}) for i in range(50)]
    store = _store_with_records(records)
    broker = MagicMock()

    with patch("aryx.resolve_entities.AdjudicationStore"), \
         patch("aryx.resolve_entities.make_workspace_store") as mock_make_ws, \
         patch("aryx.resolve_entities.get_settings",
               return_value=_settings_stub(er_min_key_selectivity=0.01, er_exact_id_match=True)), \
         patch("aryx.resolve_entities.resolve") as mock_resolve, \
         patch("aryx.resolve_entities.resolve_chunked") as mock_chunked:
        mock_make_ws.return_value.get_survivorship.return_value = {}
        mock_resolve.return_value = []
        resolve_run(run_id=1, ontology_type="Thing", key_attrs=["id"],
                   store=store, broker=broker, workspace_id=1)

    mock_resolve.assert_called_once()
    mock_chunked.assert_not_called()
    # resolve() must be called with exact_ids=True
    _, kwargs = mock_resolve.call_args
    assert kwargs["exact_ids"] is True

    mock_resolve.assert_called_once()
    mock_chunked.assert_not_called()


# ── force_exact verification (PR review M2, 2026-10-04) ─────────────────────
# force_exact is a caller's ASSERTION that a match key named too generically
# to qualify via _id_like_keys() still has unique-enough values to resolve by
# exact equality. The original implementation trusted that assertion outright
# -- a real correctness bug: cpq_ingestion's only signal is infer_match_keys_
# for_tag's source=="default", which fires whenever neither the heuristic nor
# the LLM could confidently name a key, and says nothing about whether the
# key's VALUES are unique. These tests pin the fix: force_exact must be
# independently verified against the same selectivity sample that already
# guards the low_selectivity path before it's honored.

def test_force_exact_honored_when_selectivity_confirms_uniqueness() -> None:
    """Every record has a distinct match text (selectivity 1.0) -- force_exact
    is verified and resolve() must run in exact_ids mode."""
    records = [ResolutionRecord(record_id=i, text=f"unique-{i}", payload={})
               for i in range(50)]
    store = _store_with_records(records)
    broker = MagicMock()

    with patch("aryx.resolve_entities.AdjudicationStore"), \
         patch("aryx.resolve_entities.make_workspace_store") as mock_make_ws, \
         patch("aryx.resolve_entities.get_settings",
               return_value=_settings_stub(er_exact_id_match=False,
                                            er_force_exact_min_selectivity=0.99)), \
         patch("aryx.resolve_entities.resolve") as mock_resolve, \
         patch("aryx.resolve_entities.resolve_chunked") as mock_chunked:
        mock_make_ws.return_value.get_survivorship.return_value = {}
        mock_resolve.return_value = []
        resolve_run(run_id=1, ontology_type="Thing", key_attrs=["text"],
                   store=store, broker=broker, workspace_id=1, force_exact=True)

    mock_chunked.assert_not_called()
    mock_resolve.assert_called_once()
    _, kwargs = mock_resolve.call_args
    assert kwargs["exact_ids"] is True


def test_force_exact_rejected_when_selectivity_does_not_confirm_uniqueness() -> None:
    """Only half the sampled values are distinct (selectivity 0.5) -- NOT
    unique enough to trust force_exact's assertion. Must fall through to the
    normal fuzzy path (exact_ids=False), not silently merge non-unique
    records by equality."""
    records = [ResolutionRecord(record_id=i, text=f"dup-{i % 25}", payload={})
               for i in range(50)]
    store = _store_with_records(records)
    broker = MagicMock()

    with patch("aryx.resolve_entities.AdjudicationStore"), \
         patch("aryx.resolve_entities.make_workspace_store") as mock_make_ws, \
         patch("aryx.resolve_entities.get_settings",
               return_value=_settings_stub(er_exact_id_match=False,
                                            er_min_key_selectivity=0.01,
                                            er_force_exact_min_selectivity=0.99)), \
         patch("aryx.resolve_entities.resolve") as mock_resolve, \
         patch("aryx.resolve_entities.resolve_chunked") as mock_chunked:
        mock_make_ws.return_value.get_survivorship.return_value = {}
        mock_resolve.return_value = []
        resolve_run(run_id=1, ontology_type="Thing", key_attrs=["text"],
                   store=store, broker=broker, workspace_id=1, force_exact=True)

    mock_chunked.assert_not_called()
    mock_resolve.assert_called_once()
    _, kwargs = mock_resolve.call_args
    assert kwargs["exact_ids"] is False


def test_force_exact_catches_a_duplicate_a_head_sample_would_have_missed() -> None:
    """PR review N1 (2026-10-04): the original fix reused _key_selectivity(),
    a HEAD sample (records[:sample_size]) -- a duplicate value concentrated
    outside the sampled head (e.g. a repeated 'N/A' placeholder) would make
    the sample look fully unique while the real data isn't. force_exact
    verification must scan every record, not a sample: here, a tiny
    sample_size of 3 means the first 3 records (all distinct) would have
    looked selectivity=1.0 to the old sampled check, but records 10 and 15
    (well outside that sample window) share the exact same text -- the full
    scan must still catch it and reject force_exact."""
    records = [ResolutionRecord(record_id=i, text=f"unique-{i}", payload={})
               for i in range(20)]
    records[10] = ResolutionRecord(record_id=10, text="N/A", payload={})
    records[15] = ResolutionRecord(record_id=15, text="N/A", payload={})  # duplicate, outside sample[:3]
    store = _store_with_records(records)
    broker = MagicMock()

    with patch("aryx.resolve_entities.AdjudicationStore"), \
         patch("aryx.resolve_entities.make_workspace_store") as mock_make_ws, \
         patch("aryx.resolve_entities.get_settings",
               return_value=_settings_stub(er_exact_id_match=False,
                                            er_key_selectivity_sample_size=3,
                                            er_force_exact_min_selectivity=1.0)), \
         patch("aryx.resolve_entities.resolve") as mock_resolve, \
         patch("aryx.resolve_entities.resolve_chunked") as mock_chunked:
        mock_make_ws.return_value.get_survivorship.return_value = {}
        mock_resolve.return_value = []
        resolve_run(run_id=1, ontology_type="Thing", key_attrs=["text"],
                   store=store, broker=broker, workspace_id=1, force_exact=True)

    mock_chunked.assert_not_called()
    mock_resolve.assert_called_once()
    _, kwargs = mock_resolve.call_args
    assert kwargs["exact_ids"] is False  # correctly rejected -- NOT silently merged


def test_full_uniqueness_ratio_is_computed_not_the_sampled_selectivity() -> None:
    """Pins that force_exact's verification calls _full_uniqueness_ratio
    (full scan), not _key_selectivity (sample) -- a direct regression guard
    against silently reverting to the sampled check."""
    records = [ResolutionRecord(record_id=i, text=f"unique-{i}", payload={})
               for i in range(20)]
    records[10] = ResolutionRecord(record_id=10, text="N/A", payload={})
    records[15] = ResolutionRecord(record_id=15, text="N/A", payload={})
    store = _store_with_records(records)
    broker = MagicMock()

    with patch("aryx.resolve_entities.AdjudicationStore"), \
         patch("aryx.resolve_entities.make_workspace_store") as mock_make_ws, \
         patch("aryx.resolve_entities.get_settings",
               return_value=_settings_stub(er_exact_id_match=False,
                                            er_key_selectivity_sample_size=3,
                                            er_force_exact_min_selectivity=1.0)), \
         patch("aryx.resolve_entities._full_uniqueness_ratio",
               wraps=__import__("aryx.resolve_entities_selectivity",
                                fromlist=["_full_uniqueness_ratio"])._full_uniqueness_ratio,
               ) as mock_full_scan, \
         patch("aryx.resolve_entities.resolve", return_value=[]), \
         patch("aryx.resolve_entities.resolve_chunked"):
        mock_make_ws.return_value.get_survivorship.return_value = {}
        resolve_run(run_id=1, ontology_type="Thing", key_attrs=["text"],
                   store=store, broker=broker, workspace_id=1, force_exact=True)

    mock_full_scan.assert_called_once()
    (scanned_records,), _ = mock_full_scan.call_args
    assert len(scanned_records) == 20  # the FULL set, not a 3-record sample


def test_force_exact_without_key_attrs_never_triggers_exact_mode() -> None:
    """bool(key_attrs) guard must hold for force_exact too, same as the
    name-based check -- an empty match-key list must never mean exact mode."""
    records = [ResolutionRecord(record_id=i, text=f"unique-{i}", payload={})
               for i in range(50)]
    store = _store_with_records(records)
    broker = MagicMock()

    with patch("aryx.resolve_entities.AdjudicationStore"), \
         patch("aryx.resolve_entities.make_workspace_store") as mock_make_ws, \
         patch("aryx.resolve_entities.get_settings",
               return_value=_settings_stub(er_exact_id_match=False)), \
         patch("aryx.resolve_entities.resolve") as mock_resolve, \
         patch("aryx.resolve_entities.resolve_chunked") as mock_chunked:
        mock_make_ws.return_value.get_survivorship.return_value = {}
        mock_resolve.return_value = []
        resolve_run(run_id=1, ontology_type="Thing", key_attrs=[],
                   store=store, broker=broker, workspace_id=1, force_exact=True)

    mock_chunked.assert_not_called()
    mock_resolve.assert_called_once()
    _, kwargs = mock_resolve.call_args
    assert kwargs["exact_ids"] is False


# ── cross-run duplication risk (PR #429 review N2, cpq_ingestion raw-graph
# resolve/relate re-confirm after a cancel) ─────────────────────────────────
#
# resolve_and_relate_raw_graph()'s docstring originally claimed a re-confirm
# would "merge onto" entities a cancelled attempt already created. That was
# wrong: resolve_run()/resolve() only cluster the records passed to THAT
# call against each other; they never look up entities a PRIOR run already
# saved. These tests prove it at the resolve_run level -- the same level
# every confirm and re-confirm in the system goes through -- by calling it
# twice with identical input and showing each call independently drives its
# own store.save() with its own freshly "resolved" entity, with no lookup or
# coordination between the two calls. (EntityStore.save()'s own SQL --
# insert_entity.sql, a plain INSERT with no ON CONFLICT -- was confirmed
# separately by reading it to complete the chain: two independent save()
# calls for the same logical record become two separate database rows.)
#
# KNOWN-GAP TESTS, pinning a real architectural invariant, not a bug this
# file's code is expected to fix (PR #429 review N1): resolve_run() itself
# will likely NEVER gain cross-run entity lookup -- doing so generically
# would change matching semantics for every caller in the system, not just
# cpq_ingestion. The actual mitigation for cpq_ingestion's cancel-then-
# retry case lives one layer up, in resolve_and_relate_raw_graph()'s
# _delete_orphaned_entities() (src/aryx/cpq_ingestion/raw_graph/
# resolve_relate.py): a mid-loop cancel now deletes the entities
# already-resolved tags created in THAT attempt, so a retry starts clean
# instead of piling new entities on top of the old ones. These two tests
# below will keep passing after that fix (and should keep passing after
# any future one) because they test resolve_run() in isolation, not the
# cancel-cleanup behavior -- do not take their continued passing as
# evidence the cpq_ingestion duplication risk is unaddressed; check
# resolve_relate.py's own tests (test_resolve_and_relate_raw_graph.py) for
# that instead.

def test_resolve_run_has_no_cross_run_entity_lookup_mechanism():
    """A second resolve_run() call for IDENTICAL records (as a cpq XML
    re-confirm after a cancel would produce for an already-resolved tag)
    drives its own independent store.save() call -- nothing in resolve_run
    or the mocked resolve() ever consults what a prior run_id already
    saved. This is true regardless of whether key_attrs is a real match
    key, empty, or anything else -- the duplication risk is NOT limited to
    keyless/LLM-guessed tags, contrary to a narrower reading of the
    original review comment."""
    records = [ResolutionRecord(record_id=1, text="Acme Corp", payload={"name": "Acme Corp"})]
    store = _store_with_records(records)
    broker = MagicMock()

    same_entity_each_time = [
        (ResolvedEntity(ontology_type="Company", attributes={"name": "Acme Corp"}),
         [EntityMember(landed_record_id=1)]),
    ]

    with patch("aryx.resolve_entities.AdjudicationStore"), \
         patch("aryx.resolve_entities.make_workspace_store") as mock_make_ws, \
         patch("aryx.resolve_entities.resolve", return_value=same_entity_each_time) as mock_resolve:
        mock_make_ws.return_value.get_survivorship.return_value = {}

        # First "confirm attempt" -- run_id=1.
        resolve_run(run_id=1, ontology_type="Company", key_attrs=["name"],
                   store=store, broker=broker, workspace_id=1)
        # A cancelled-and-re-confirmed attempt gets a NEW run_id (run_id=2)
        # for the exact same source records -- nothing in this call chain
        # is told run_id=1 already resolved them.
        resolve_run(run_id=2, ontology_type="Company", key_attrs=["name"],
                   store=store, broker=broker, workspace_id=1)

    assert mock_resolve.call_count == 2
    assert store.save.call_count == 2
    # Both save() calls receive the SAME "resolved" entity payload --
    # production EntityStore.save() would INSERT it twice (no ON CONFLICT,
    # no pre-check), i.e. two distinct entity rows for the same data.
    first_call_results = store.save.call_args_list[0].args[0]
    second_call_results = store.save.call_args_list[1].args[0]
    assert first_call_results == second_call_results == same_entity_each_time


def test_resolve_run_duplication_risk_is_independent_of_key_attrs():
    """Same proof as above, but with key_attrs=[] (no match key at all) --
    the review comment's specific concern. The outcome is identical: two
    independent resolve_run() calls, two independent store.save() calls,
    regardless of key_attrs content."""
    records = [ResolutionRecord(record_id=1, text="some script body", payload={})]
    store = _store_with_records(records)
    broker = MagicMock()

    same_entity_each_time = [
        (ResolvedEntity(ontology_type="Script", attributes={}), [EntityMember(landed_record_id=1)]),
    ]

    with patch("aryx.resolve_entities.AdjudicationStore"), \
         patch("aryx.resolve_entities.make_workspace_store") as mock_make_ws, \
         patch("aryx.resolve_entities.resolve", return_value=same_entity_each_time) as mock_resolve:
        mock_make_ws.return_value.get_survivorship.return_value = {}

        resolve_run(run_id=1, ontology_type="Script", key_attrs=[],
                   store=store, broker=broker, workspace_id=1)
        resolve_run(run_id=2, ontology_type="Script", key_attrs=[],
                   store=store, broker=broker, workspace_id=1)

    assert mock_resolve.call_count == 2
    assert store.save.call_count == 2
