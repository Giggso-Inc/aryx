"""Typed errors for the csv_bml_ingestion pipeline.

Each carries a stable ``code`` (also used as the Raven ``error_code``) so a
caller or log search can tell the failure modes apart without parsing text.
"""
from __future__ import annotations


class CsvBmlIngestionError(Exception):
    """Base class; ``code`` doubles as the Raven error_code."""

    code = "CBI_ERROR"


class TableNameMissingError(CsvBmlIngestionError):
    """The target table name could not be extracted from the CSV filename."""

    code = "CBI_TABLE_NAME_MISSING"


class InvalidTableNameError(CsvBmlIngestionError):
    """The extracted table name is not a safe SQL identifier."""

    code = "CBI_TABLE_NAME_INVALID"


class XmlSourceError(CsvBmlIngestionError):
    """The XML source could not be read or parsed into a graph."""

    code = "CBI_XML_SOURCE"


class BmlQueryNotFoundError(CsvBmlIngestionError):
    """No BML script in the XML graph queries the target table."""

    code = "CBI_BML_NOT_FOUND"


class SqlArtifactsMissingError(CsvBmlIngestionError):
    """A BML query exists but its schema/index .sql files have not been generated."""

    code = "CBI_SQL_ARTIFACTS_MISSING"


class CsvFormatError(CsvBmlIngestionError):
    """The CSV does not follow the ``_start/_end meta data`` layout or is unreadable."""

    code = "CBI_CSV_FORMAT"


class DatabaseUnavailableError(CsvBmlIngestionError):
    """The relational backend is not configured for this ingestion."""

    code = "CBI_DB_UNAVAILABLE"


class ValueTooLongError(CsvBmlIngestionError):
    """A CSV value does not fit its column and the overflow policy is ``fail``."""

    code = "CBI_VALUE_TOO_LONG"


class SchemaMismatchError(CsvBmlIngestionError):
    """The CSV has columns the database table does not (or the table is missing)."""

    code = "CBI_SCHEMA_MISMATCH"
