"""Exact-identity resolution for id-keyed data (CM-1).

Fuzzy similarity is invalid for opaque ids: sequential ids like
18722401146/18722401147 score 0.909+ and transitively collapse whole ranges.
Exact mode merges on normalized-text equality only.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from aryx.models import ResolutionRecord
from aryx.resolution.run import resolve


def _rec(rid: int, text: str) -> ResolutionRecord:
    return ResolutionRecord(record_id=rid, text=text, payload={"id": text})


def test_identical_ids_merge() -> None:
    results = resolve([_rec(1, "18722401146"), _rec(2, "18722401146")],
                      MagicMock(), "T", exact_ids=True)
    assert len(results) == 1
    entity, members = results[0]
    assert {m.landed_record_id for m in members} == {1, 2}
    assert entity.confidence == 0.99  # chain edge at 1.0, clamped


def test_near_ids_never_merge() -> None:
    """The exact pair that caused the production over-merge (0.909 fuzzy score)."""
    results = resolve([_rec(1, "18722401146"), _rec(2, "18722401147")],
                      MagicMock(), "T", exact_ids=True)
    assert len(results) == 2


def test_empty_text_never_merges() -> None:
    """Blank match text must not group — '' vs '' scores 1.0 on the fuzzy path."""
    results = resolve([_rec(1, ""), _rec(2, ""), _rec(3, "  ")],
                      MagicMock(), "T", exact_ids=True)
    assert len(results) == 3


def test_normalization_applies() -> None:
    """Whitespace/case variants of the same id are the same identity."""
    results = resolve([_rec(1, "ABC-1"), _rec(2, " abc-1 ")],
                      MagicMock(), "T", exact_ids=True)
    assert len(results) == 1


def test_exact_mode_makes_no_broker_calls() -> None:
    broker = MagicMock()
    resolve([_rec(1, "a1"), _rec(2, "a2")], broker, "T", exact_ids=True)
    broker.embed.assert_not_called()
    broker.complete.assert_not_called()


class _Settings:
    er_exact_id_match = True
    max_pairs_per_block = 500
    embed_batch_size = 50
    er_auto_merge = 0.92
    er_adjudicate = 0.90
    er_review = 0.75
    max_block_size = 5000
    rdb_dsn = "postgresql://x"


def _detect(key_attrs: list[str], flag: bool = True) -> bool:
    """Mirror of resolve_run's detection expression, kept in sync by the wiring test."""
    from aryx.resolve_entities import _ID_LIKE_KEYS
    s = _Settings()
    s.er_exact_id_match = flag
    return (s.er_exact_id_match and bool(key_attrs)
            and all(k.lower() in _ID_LIKE_KEYS for k in key_attrs))


def test_detection_id_like_keys() -> None:
    assert _detect(["id"]) is True
    assert _detect(["GUID"]) is True
    assert _detect(["id", "uuid"]) is True


def test_detection_mixed_keys_stay_fuzzy() -> None:
    assert _detect(["id", "name"]) is False
    assert _detect(["name"]) is False


def test_detection_empty_keys_stay_fuzzy() -> None:
    """all([]) is True — the bool(key_attrs) guard is load-bearing."""
    assert _detect([]) is False


def test_detection_flag_off_restores_fuzzy() -> None:
    assert _detect(["id"], flag=False) is False


def test_resolve_run_wires_exact_ids_through() -> None:
    """End-to-end: id-keyed run uses exact mode (near-ids stay separate)."""
    from aryx.resolve_entities import resolve_run

    store = MagicMock()
    store.landed_records.return_value = [_rec(1, "18722401146"), _rec(2, "18722401147")]
    store.save.side_effect = lambda results: len(results)

    with patch("aryx.resolve_entities.AdjudicationStore"), \
         patch("aryx.resolve_entities.make_workspace_store") as ws, \
         patch("aryx.resolve_entities.get_settings", return_value=_Settings()):
        ws.return_value.get_survivorship.return_value = {}
        created = resolve_run(1, "T", ["id"], store, MagicMock(), workspace_id=1)

    assert created == 2  # near-ids NOT merged
