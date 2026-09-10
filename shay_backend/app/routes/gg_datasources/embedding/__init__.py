"""
Embedding-status / ML-webhook endpoints:

  GET    /embedding-status/{scope_level}/{scope_id}
  POST   /embedding/webhook              ML callback (no auth — called by the ML service)
  POST   /embedding/regenerate/{datasource_id}

Split into one module per endpoint (Raven style-compliance, wave B4) —
each was previously a section of a single 208-line embedding.py. Combined
here via router.include_router() so `from . import embedding;
router.include_router(embedding.router)` in the package __init__.py needs
no changes.
"""

from fastapi import APIRouter

from . import regenerate
from . import status
from . import webhook

router = APIRouter()
router.include_router(status.router)
router.include_router(webhook.router)
router.include_router(regenerate.router)
