"""CSV source connector: each row becomes a RawRecord."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
from collections.abc import Iterator
from pathlib import Path

from aryx.connectors.base import Connector
from aryx.models import RawRecord, SourceRef

logger = logging.getLogger(__name__)

_META_START = "_start meta data"
_META_END = "_end meta data"
_META_SCAN_LIMIT = 10  # _end meta data has always been on line 5 in every real export seen


def _strip_oracle_cpq_meta_block(text: str) -> str:
    """Oracle CPQ Data Table exports (whitelist.csv, attrSequence.csv,
    CPQModelHierarchy.csv, etc.) open with a 5-line metadata block:

        _start meta data
        <real header row>
        <column-type row, e.g. "String,String,Integer,...">
        <blank/placeholder row>
        _end meta data

    csv.DictReader always treats line 1 as the header -- left alone, it
    reads the literal text "_start meta data" as a one-column header, and
    the REAL header row two lines down gets ingested as a garbage data row
    (confirmed live: every ingested entity ended up with a single bogus
    "_start meta data" key). Detected here and stripped before parsing;
    files that don't start with this exact marker are returned unchanged --
    zero behavior change for any other CSV.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != _META_START:
        return text
    end_idx = None
    for i in range(1, min(len(lines), _META_SCAN_LIMIT)):
        if lines[i].strip() == _META_END:
            end_idx = i
            break
    if end_idx is None or end_idx < 2:
        # No matching _end meta data found nearby, or nothing between the
        # markers to have been a real header -- not this shape, leave as-is
        # rather than guess.
        return text
    real_header = lines[1]
    data_rows = lines[end_idx + 1:]
    return "\n".join([real_header, *data_rows])


class CsvConnector(Connector):
    """Read a CSV file (or bytes) into RawRecords, one per row."""

    def __init__(self, source: Path | bytes, system: str = "csv",
                 dataset: str = "upload") -> None:
        self._source = source
        self._system = system
        self._dataset = dataset

    def extract(self) -> Iterator[RawRecord]:
        if isinstance(self._source, bytes):
            text = self._source.decode("utf-8")
        else:
            text = self._source.open(encoding="utf-8").read()
        reader = csv.DictReader(io.StringIO(_strip_oracle_cpq_meta_block(text)))
        count = 0
        for row in reader:
            # DictReader stores extra-column values under the None key when a row
            # has more fields than the header (restkey=None default). Drop those
            # extra values: they are positionally meaningless and cause
            # json.dumps(sort_keys=True) to crash with NoneType < str.
            clean_row = {k: v for k, v in row.items() if k is not None}
            record_id = hashlib.sha256(
                json.dumps(clean_row, sort_keys=True).encode()
            ).hexdigest()[:16]
            yield RawRecord(
                source=SourceRef(system=self._system, dataset=self._dataset,
                                 record_id=record_id),
                payload=clean_row,
            )
            count += 1
        logger.info("csv extracted dataset=%s records=%d", self._dataset, count)
