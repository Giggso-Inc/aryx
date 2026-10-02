"""Shared fixtures: a tiny BML-bearing XML, CSV files, and a fake DB connection."""
from __future__ import annotations

import re
import shutil
from contextlib import contextmanager
from pathlib import Path

import pytest

from aryx.csv_bml_ingestion.bml_index import BmlIndex

BML_XML = b"""<?xml version="1.0"?>
<bm_config_zip_cache>
  <bm_function>
    <id>111</id>
    <guid><![CDATA[guid-111]]></guid>
    <java_class_name>com.bm.Action_111</java_class_name>
    <script_text><![CDATA[
// BMQL("SELECT x FROM commentedOut WHERE a=1");
attrSeqTableName = "attrSequence";
if (isnull(attrSeqTableName)) { attrSeqTableName = jsonget(j, "ATTR_SEQUENCE"); }
rs = BMQL("SELECT AttrName,Seq FROM $attrSeqTableName WHERE CPQModel=$m
   ORDER BY Seq");
rs2 = bmql("SELECT attr1 FROM attrToPDNonFrequency " + "WHERE cpqModel=$m");
rs3 = BMQL("SELECT partNumber FROM attrToPart_pcrDev WHERE model=$m");
rs4 = BMQL(dynamicQuery);
]]></script_text>
  </bm_function>
</bm_config_zip_cache>"""


FIXTURE_SQL = Path(__file__).parent / "fixtures" / "sql"   # agent-authored examples (test data only)


@pytest.fixture(autouse=True)
def seeded_sql_root(tmp_path, monkeypatch) -> Path:
    """Point the pipeline at a temp SQL folder pre-seeded with two authored tables."""
    root = tmp_path / "sql_root"
    shutil.copytree(FIXTURE_SQL, root)
    monkeypatch.setenv("ARYX_CSV_BML_SQL_DIR", str(root))
    return root


@pytest.fixture(scope="session")
def bml_index() -> BmlIndex:
    return BmlIndex.from_xml_bytes(BML_XML)


class FakeCursor:
    def __init__(self, log: list, catalog: dict, comments: dict) -> None:
        self.log, self.catalog, self.comments, self._rows = log, catalog, comments, []

    def execute(self, sql: str, params=None) -> None:
        self.log.append(("execute", sql))
        m = re.match(r"CREATE TABLE IF NOT EXISTS (\w+) \((.*)\)$", sql)
        if m:  # remember the declared columns so user_tab_columns can answer like Oracle
            self.catalog[m.group(1).upper()] = [
                (n.upper(), "VARCHAR2", int(n_len), int(n_len), "B", None, None)
                for n, n_len in re.findall(r"(\w+) VARCHAR2\((\d+)\)", m.group(2))
            ] + [(n.upper(), "NUMBER", 22, None, None, int(p), 0)
                 for n, p in re.findall(r"(\w+) NUMBER\((\d+)\)", m.group(2))]
        cm = re.match(r"COMMENT ON TABLE (\w+) IS '([^']*)'", sql)
        if cm:
            self.comments[cm.group(1).upper()] = cm.group(2)
        if "user_tab_comments" in sql:
            self._rows = [(self.comments.get(params[0]),)] if params[0] in self.catalog else []
        if "user_tab_columns" in sql:
            self._rows = self.catalog.get(params[0], [])

    def fetchall(self) -> list:
        return self._rows

    def executemany(self, sql: str, rows) -> None:
        self.log.append(("executemany", sql, list(rows)))


class FakeDb:
    """Records every statement; ``fail_on`` makes a matching statement raise."""

    def __init__(self, fail_on: str | None = None) -> None:
        self.log: list = []
        self.catalog: dict = {}
        self.comments: dict = {}
        self.fail_on = fail_on
        self.committed = 0
        self.rolled_back = 0

    @contextmanager
    def __call__(self):
        db = self

        class Conn:
            def cursor(self_inner):  # noqa: N805
                cur = FakeCursor(db.log, db.catalog, db.comments)
                if db.fail_on:
                    orig = cur.executemany

                    def boom(sql, rows):
                        if db.fail_on in sql:
                            raise RuntimeError("ORA-boom")
                        orig(sql, rows)
                    cur.executemany = boom  # type: ignore[method-assign]
                return cur

        try:
            yield Conn()
            self.committed += 1
        except Exception:
            self.rolled_back += 1
            raise

    def writes(self) -> list:
        """Everything that changed (or could change) data: DDL, DML, COMMENT. Reads (SELECT) excluded."""
        return [e for e in self.log if e[0] == "executemany" or not e[1].startswith("SELECT")]

    def statements(self, kind: str) -> list:
        return [e for e in self.log if e[0] == kind]


def write_csv(path: Path, header: list[str], types: list[str], rows: list[list[str]]) -> Path:
    lines = ["_start meta data", ",".join(header), ",".join(types), "," * (len(header) - 1),
             "_end meta data", *(",".join(r) for r in rows)]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
