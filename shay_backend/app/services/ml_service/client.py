"""
MLService - assembles the request/status/delete mixins into the public
MLService class used to talk to the ML API.

Split out of the former app/services/ml_service.py (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a).
"""

from app.core.config import settings

from .delete import DeleteMixin
from .request import RequestEmbeddingMixin
from .status import StatusMixin


class MLService(RequestEmbeddingMixin, StatusMixin, DeleteMixin):
    """Service for interacting with ML API for embedding processing"""

    def __init__(self):
        self.ml_api_url = getattr(settings, "ML_API_URL", "https://dev-fourd.shay-ai.com")
        self.ml_api_key = getattr(settings, "ML_API_KEY", "")
        self.timeout = None


# Global instance
ml_service = MLService()
