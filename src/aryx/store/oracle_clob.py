"""CLOB-sizing helpers for Oracle bind parameters.

Oracle thin client binds Python str as VARCHAR2 by default (max 32767
bytes); strings longer than this must be typed as DB_TYPE_CLOB before
execute(), otherwise the TTC layer raises ORA-03146. MERGE statements need
ALL string binds to CLOB columns typed as CLOB regardless of length (Oracle
analyses both UPDATE and INSERT branches before evaluating the ON
condition), while ON-clause comparison keys must stay VARCHAR2 (ORA-22848
forbids CLOB there) -- this is exactly where this project's PR #310-#311
production bugs lived.

Split out of `store/oracle_pool.py` (Raven Style Compliance Plan, Phase 2a,
2026-09-03).
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_ORACLE_VARCHAR2_MAX = 32767


def _hint_clob(cursor: Any, params: Any, oracledb: Any) -> None:
    """Call setinputsizes for any string param that exceeds VARCHAR2 max length.

    Named params (dict): setinputsizes(**{name: DB_TYPE_CLOB, ...})
    Positional params (list/tuple): setinputsizes(*[DB_TYPE_CLOB or None, ...])
    No-op when params is None or contains no oversized strings.
    """
    if params is None:
        return
    if isinstance(params, dict):
        hints = {
            k: oracledb.DB_TYPE_CLOB
            for k, v in params.items()
            if isinstance(v, str) and len(v.encode("utf-8")) > _ORACLE_VARCHAR2_MAX
        }
        if hints:
            logger.debug("clob_hint named keys=%s", list(hints))
            cursor.setinputsizes(**hints)
    elif isinstance(params, (list, tuple)):
        sizes = [
            oracledb.DB_TYPE_CLOB
            if isinstance(v, str) and len(v.encode("utf-8")) > _ORACLE_VARCHAR2_MAX
            else None
            for v in params
        ]
        if any(s is not None for s in sizes):
            logger.debug("clob_hint positional count=%d", sum(1 for s in sizes if s))
            cursor.setinputsizes(*sizes)


def _coerce_clob(
    params: Any,
    cursor: Any,
    oracledb: Any,
    force: bool = False,
    exclude: "frozenset[str] | None" = None,
) -> Any:
    """Replace strings with oracledb CLOB var objects IN PLACE OF the value.

    When force=False (default): only replaces strings >32767 bytes — sufficient for
    plain INSERT/UPDATE where Oracle can coerce short VARCHAR2 to CLOB implicitly.

    When force=True: replaces ALL strings regardless of length — required for MERGE
    statements where Oracle analyses bind types across both UPDATE and INSERT branches
    simultaneously.  VARCHAR2-typed binds to CLOB columns in MERGE trigger ORA-03146
    even for short strings.

    exclude: set of named param keys that must NOT be coerced (e.g. MERGE ON-clause
    keys used as comparison predicates — Oracle raises ORA-22848 if they are CLOB).
    """
    if params is None:
        return params
    threshold = -1 if force else _ORACLE_VARCHAR2_MAX
    excl = exclude or frozenset()
    if isinstance(params, dict):
        out: dict[str, Any] = {}
        for k, v in params.items():
            if k not in excl and isinstance(v, str) and len(v.encode("utf-8")) > threshold:
                cvar = cursor.var(oracledb.DB_TYPE_CLOB)
                cvar.setvalue(0, v)
                out[k] = cvar
            else:
                out[k] = v
        return out
    if isinstance(params, (list, tuple)):
        out_list: list[Any] = []
        for v in params:
            if isinstance(v, str) and len(v.encode("utf-8")) > threshold:
                cvar = cursor.var(oracledb.DB_TYPE_CLOB)
                cvar.setvalue(0, v)
                out_list.append(cvar)
            else:
                out_list.append(v)
        return tuple(out_list) if isinstance(params, tuple) else out_list
    return params


def _hint_clob_many(
    cursor: Any,
    seq: list[Any],
    oracledb: Any,
    force_merge: bool = False,
    on_excl: "frozenset[str]" = frozenset(),
) -> None:
    """Call setinputsizes for executemany: scans ALL rows to find oversized strings.

    Necessary because different rows in the batch may have different payload sizes —
    e.g. entity attributes where some rows carry large XML/JSON content and others don't.
    One setinputsizes call covers the whole executemany batch.

    force_merge=True: hint ALL string-valued named keys (except those in on_excl) as
    DB_TYPE_CLOB regardless of length.  Required for MERGE statements — Oracle analyses
    both UPDATE and INSERT branches simultaneously, so VARCHAR2-typed binds to CLOB/JSON
    columns trigger ORA-03146 even for short strings.  on_excl must hold the ON-clause
    bind names (ORA-22848 forbids CLOB in comparison predicates).
    """
    if not seq:
        return
    first = seq[0]
    if isinstance(first, dict):
        clob_keys: set[str] = set()
        if force_merge:
            # Force-hint all string-valued keys that are not ON-clause keys.
            for row in seq:
                if isinstance(row, dict):
                    for k, v in row.items():
                        if k not in clob_keys and k not in on_excl and isinstance(v, str):
                            clob_keys.add(k)
        else:
            for row in seq:
                if isinstance(row, dict):
                    for k, v in row.items():
                        if k not in clob_keys and isinstance(v, str) and len(v.encode("utf-8")) > _ORACLE_VARCHAR2_MAX:
                            clob_keys.add(k)
        if clob_keys:
            logger.debug("clob_hint_many named keys=%s force_merge=%s", sorted(clob_keys), force_merge)
            cursor.setinputsizes(**{k: oracledb.DB_TYPE_CLOB for k in clob_keys})
    elif isinstance(first, (list, tuple)):
        n_cols = len(first)
        sizes: list[Any] = [None] * n_cols
        for row in seq:
            if isinstance(row, (list, tuple)):
                for i, v in enumerate(row):
                    if sizes[i] is None and isinstance(v, str) and len(v.encode("utf-8")) > _ORACLE_VARCHAR2_MAX:
                        sizes[i] = oracledb.DB_TYPE_CLOB
        if any(s is not None for s in sizes):
            logger.debug("clob_hint_many positional count=%d", sum(1 for s in sizes if s))
            cursor.setinputsizes(*sizes)
