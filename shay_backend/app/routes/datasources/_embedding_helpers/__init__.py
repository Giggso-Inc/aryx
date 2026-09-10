"""
Embedding-status / vault-token / Aryx-status query helpers shared across
datasource create, bulk, embedding-status, and download routes.

Private package: used by create.py, bulk_create.py, bulk_create_internal.py,
embedding_status.py, embedding_regenerate.py, and download_datasource.py
(and their _*.py helper files), all via `from ._embedding_helpers import
<name>` — this __init__ re-exports every name so none of those imports need
to change.

Split into one module per independent query/lookup (Raven style-compliance,
wave B4) — previously a single 165-line _embedding_helpers.py holding five
functions that share no internal state.
"""

from ._aryx_status import _aryx_ingestion_status_for
from ._scope_queries import get_completed_embeddings_by_channel, get_completed_embeddings_by_thread
from ._status_update import update_embedding_status_batch
from ._vault_token import get_openai_vault_token_for_company

__all__ = [
    "_aryx_ingestion_status_for",
    "get_openai_vault_token_for_company",
    "get_completed_embeddings_by_channel",
    "get_completed_embeddings_by_thread",
    "update_embedding_status_batch",
]
