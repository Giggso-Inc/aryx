"""
ML API Service for handling embedding requests

--------------------------------------------------------------------------
Package split (Raven style-compliance pass, see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a): this used to be a
single 478-line app/services/ml_service.py. It is now a package of
submodules by responsibility:
  - helpers.py: extract_table_names_from_datasources, get_embedd_type_from_file_type
                (pure helpers, no HTTP dependency)
  - request.py: RequestEmbeddingMixin (request_embedding_processing)
  - status.py:  StatusMixin (check_embedding_status)
  - delete.py:  DeleteMixin (delete_embeddings)
  - client.py:  MLService (combines the three mixins) + the module-level
                `ml_service` instance

All names below are re-exported so `from app.services.ml_service import
ml_service`, `... import extract_table_names_from_datasources`, `...
import get_embedd_type_from_file_type`, and `... import MLService` (all used
throughout app/routes/datasources and app/routes/gg_datasources, plus the
existing tests/test_ml_service_embedd_type.py, tests/test_embedd_type_final.py,
tests/test_simple.py, tests/test_services.py) need zero changes.
"""

from .client import MLService, ml_service
from .helpers import extract_table_names_from_datasources, get_embedd_type_from_file_type

__all__ = [
    "MLService",
    "ml_service",
    "extract_table_names_from_datasources",
    "get_embedd_type_from_file_type",
]
