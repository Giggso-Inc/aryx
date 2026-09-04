"""
Token details routes (non-public).

This module provides authenticated endpoints to update token details stored in the
external vault and referenced by the gg_vault table.

--------------------------------------------------------------------------
Package split (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2): this used
to be a single 767-line app/routes/token_details.py. It is now a package of
submodules by endpoint, combined into one `router` below so that
`from app.routes import token_details` / `token_details.router` (used by
main.py's route registration) needs zero changes.

All four routes are literal (non-dynamic) paths with no collision risk, so
registration order is preserved as a courtesy to match the original file's
declaration order, not because it is load-bearing here.

`_normalize_token_type_for_vault` is re-exported because
app/routes/public/vault.py and app/routes/public/signup.py import it
directly as `from app.routes.token_details import
_normalize_token_type_for_vault` — that import path must keep working.
"""

from fastapi import APIRouter

from . import update
from . import fetch
from . import delete
from . import validation
from .helpers import (
    _normalize_token_type_for_vault,
    _vault_dict_to_ml_shape,
    _vault_dict_to_response_shape,
)

router = APIRouter()
router.include_router(update.router)
router.include_router(fetch.router)
router.include_router(delete.router)
router.include_router(validation.router)

__all__ = [
    "router",
    "_normalize_token_type_for_vault",
    "_vault_dict_to_ml_shape",
    "_vault_dict_to_response_shape",
]
