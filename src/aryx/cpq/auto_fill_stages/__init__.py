"""`resolve_one_attr`'s stage cluster (docs/RAVEN_STYLE_COMPLIANCE_PLAN_
2026-09-03.md, the `auto_fill_resolve` split).

Deliberately empty of re-exports: `aryx.cpq.auto_fill.auto_fill_resolve` stays the
single public entry point (`resolve_one_attr`), and every stage module
imports its siblings by full path, so nothing here needs to import a
submodule at package-import time (`auto_fill_resolve` is itself imported
from a partially-initialized `aryx.cpq.engine`, so the fewer import-time
side effects in this package the better).
"""
from __future__ import annotations
