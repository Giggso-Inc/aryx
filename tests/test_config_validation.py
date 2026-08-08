"""Regression coverage for Settings field validation.

Raven review finding: ingest_workers, max_block_size, and worker_threads
were plain `int` fields with no lower bound. ARYX_INGEST_WORKERS=0 crashes at
ThreadPoolExecutor(max_workers=0) (raises ValueError there instead of at
config load time, so the failure surfaces far from its actual cause).
ARYX_MAX_BLOCK_SIZE=0 causes every non-empty block to be skipped, silently
dropping all entity resolution with no error at all. ARYX_WORKER_THREADS=0
crashes inside ProcessPoolExecutor(max_workers=0) after the ingest job has
already been created and returned to the caller as "queued", leaving it
stuck with no terminal status. All three must fail fast at Settings
construction instead.

_env_file=None on every construction here so these tests are unaffected by
whatever a developer's local .env file happens to contain.
"""
from __future__ import annotations

import pytest

from aryx.config import Settings


class TestIngestWorkersValidation:
    def test_zero_is_rejected(self):
        with pytest.raises(Exception):
            Settings(_env_file=None, ingest_workers=0)

    def test_negative_is_rejected(self):
        with pytest.raises(Exception):
            Settings(_env_file=None, ingest_workers=-1)

    def test_positive_is_accepted(self):
        assert Settings(_env_file=None, ingest_workers=5).ingest_workers == 5

    def test_default_is_valid(self):
        assert Settings(_env_file=None).ingest_workers >= 1


class TestMaxBlockSizeValidation:
    def test_zero_is_rejected(self):
        with pytest.raises(Exception):
            Settings(_env_file=None, max_block_size=0)

    def test_negative_is_rejected(self):
        with pytest.raises(Exception):
            Settings(_env_file=None, max_block_size=-100)

    def test_positive_is_accepted(self):
        assert Settings(_env_file=None, max_block_size=1000).max_block_size == 1000

    def test_default_is_valid(self):
        assert Settings(_env_file=None).max_block_size >= 1


class TestWorkerThreadsValidation:
    def test_zero_is_rejected(self):
        with pytest.raises(Exception):
            Settings(_env_file=None, worker_threads=0)

    def test_negative_is_rejected(self):
        with pytest.raises(Exception):
            Settings(_env_file=None, worker_threads=-1)

    def test_positive_is_accepted(self):
        assert Settings(_env_file=None, worker_threads=8).worker_threads == 8

    def test_default_is_valid(self):
        assert Settings(_env_file=None).worker_threads >= 1
