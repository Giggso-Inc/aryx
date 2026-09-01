"""_partition_pair_scores: bucket pair_scores by cluster root ONCE.

Regression coverage for a real incident: _materialize() -> cluster_edges()
scans its entire pair_scores argument for every cluster. Passing the same
run-wide dict to every cluster made total cost scale as clusters x edges
instead of just edges (~106,000 clusters x 14.3M edges = over a trillion
dict-item checks for one real run). Partitioning once, before materializing
any cluster, restores O(edges + clusters).
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from aryx.models import ResolutionRecord
from aryx.resolution.cluster import UnionFind
from aryx.resolution.run import _partition_pair_scores, resolve


def test_partition_groups_pairs_by_their_clusters_root() -> None:
    union = UnionFind()
    for i in range(6):
        union.add(i)
    union.union(0, 1)
    union.union(2, 3)
    # 4, 5 stay singletons.

    pair_scores = {(0, 1): 0.95, (2, 3): 0.90}
    by_root = _partition_pair_scores(union, pair_scores)

    root_01 = union.find(0)
    root_23 = union.find(2)
    assert by_root[root_01] == {(0, 1): 0.95}
    assert by_root[root_23] == {(2, 3): 0.90}
    assert len(by_root) == 2  # only clusters that actually have edges


def test_partition_empty_pair_scores_returns_empty() -> None:
    union = UnionFind()
    union.add(1)
    assert _partition_pair_scores(union, {}) == {}


def test_resolve_gives_each_cluster_only_its_own_pair_scores() -> None:
    """End-to-end through resolve(): each cluster's _materialize() call must
    see only its own relevant pair_scores subset, not the full run dict."""
    records = [
        ResolutionRecord(record_id=1, text="Acme Corp", payload={"name": "Acme Corp"}),
        ResolutionRecord(record_id=2, text="Acme Corp", payload={"name": "Acme Corp"}),
        ResolutionRecord(record_id=3, text="Globex Inc", payload={"name": "Globex Inc"}),
        ResolutionRecord(record_id=4, text="Globex Inc", payload={"name": "Globex Inc"}),
    ]
    broker = MagicMock()
    broker.embed.return_value = []  # force string-only scoring

    seen_sizes = []
    import aryx.resolution.run as run_module
    original_materialize = run_module._materialize

    def spy_materialize(member_ids, by_id, pair_scores, ontology_type, policy):
        seen_sizes.append(len(pair_scores))
        return original_materialize(member_ids, by_id, pair_scores, ontology_type, policy)

    with patch("aryx.resolution.run.get_settings") as mock_settings, \
         patch("aryx.resolution.run._materialize", side_effect=spy_materialize):
        mock_settings.return_value.er_auto_merge = 0.9
        mock_settings.return_value.er_adjudicate = 0.85
        mock_settings.return_value.er_review = 0.7
        mock_settings.return_value.embed_batch_size = 50
        mock_settings.return_value.max_pairs_per_block = 500

        results = resolve(records, broker, "Company")

    assert len(results) == 2  # {Acme, Acme} and {Globex, Globex}
    # Each cluster must only see its own within-cluster pair, never the
    # other cluster's — proving partitioning, not a shared full dict.
    for size in seen_sizes:
        assert size <= 1
