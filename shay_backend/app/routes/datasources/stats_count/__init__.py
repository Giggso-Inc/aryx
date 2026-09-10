"""
Datasource /stats and /count endpoints.

Split into one module per endpoint plus a shared _helpers.py (Raven
style-compliance, wave B4) — previously a single 189-line stats_count.py.
Combined here via router.include_router() so `from . import stats_count;
router.include_router(stats_count.router)` in the package __init__.py
needs no changes.
"""

from fastapi import APIRouter

from . import count
from . import stats

router = APIRouter()
router.include_router(stats.router)
router.include_router(count.router)
