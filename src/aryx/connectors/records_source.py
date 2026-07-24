"""Connector that yields a pre-built list of RawRecords (no source re-read).

Used by the document self-discovery flow: mentions are extracted once during
the read step, then a confirmed subset is ingested without re-reading the files.
"""
from __future__ import annotations

import logging
from collections.abc import Iterator

from aryx.connectors.base import Connector
from aryx.models import RawRecord

logger = logging.getLogger(__name__)


class RecordsConnector(Connector):
    """Replays an in-memory list of RawRecords into the pipeline."""

    def __init__(self, records: list[RawRecord], label: str | None = None) -> None:
        self._records = records
        self._label = label

    def extract(self) -> Iterator[RawRecord]:
        yield from self._records
        logger.info("records extracted label=%s records=%d", self._label, len(self._records))
