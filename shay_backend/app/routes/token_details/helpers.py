"""
Shared vault-shape helpers for the token_details route package.

Split out of the original app/routes/token_details.py (767 lines) as part of
the Raven style-compliance file-splitting pass (see
docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, Phase 5a item 2).
`_normalize_token_type_for_vault` is imported directly by
app/routes/public/vault.py and app/routes/public/signup.py
(`from app.routes.token_details import _normalize_token_type_for_vault`), so
it must stay importable at that path — the package's `__init__.py`
re-exports it for exactly that reason.

`_vault_dict_to_ml_shape` is defined but not called anywhere in this
codebase (grep confirms no callers in app/routes/token_details.py itself or
elsewhere) — a pre-existing dead-code helper, carried over unchanged rather
than removed, since removing unused-but-public-looking helpers is out of
scope for a line-count-only split.
"""

from __future__ import annotations


def _normalize_token_type_for_vault(token_type: str) -> str:
    """
    Normalize token_type for vault/ML: azureopenai -> azure; others (openai, chatgpt, gemini) unchanged.
    ML expects tokenType: azure | openai | chatgpt | gemini.
    """
    if not token_type:
        return token_type or ""
    t = (token_type or "").strip().lower()
    if t == "azureopenai":
        return "azure"
    return token_type.strip()


def _vault_dict_to_ml_shape(data: dict) -> dict:
    """
    Map vault keys to ML-expected keys. Handles both new (ML) and legacy vault shapes.
    ML expects: openaiToken, tokenType, model, apiVersion, endpoint, deploymentName, embeddingsDeploymentName.
    """
    if not isinstance(data, dict):
        return data
    out = dict(data)
    # tokenType: from token_type or tokenType, normalized (azureopenai -> azure)
    raw_token_type = out.get("token_type") or out.get("tokenType") or ""
    out["tokenType"] = _normalize_token_type_for_vault(raw_token_type)
    out.pop("token_type", None)
    # model: from gpt_model or model
    if "gpt_model" in out and "model" not in out:
        out["model"] = out.pop("gpt_model", "")
    # apiVersion: from deploymentVersion or apiVersion
    if "deploymentVersion" in out and "apiVersion" not in out:
        out["apiVersion"] = out.pop("deploymentVersion", "")
    # embeddingsDeploymentName: from embedding_model or embeddingsDeploymentName
    if "embedding_model" in out and "embeddingsDeploymentName" not in out:
        out["embeddingsDeploymentName"] = out.pop("embedding_model", "")
    # Remove legacy api_key if openaiToken is present (avoid duplicate)
    if "openaiToken" in out:
        out.pop("api_key", None)
    return out


def _vault_dict_to_response_shape(data: dict) -> dict:
    """
    Convert vault data (ML or legacy keys) to legacy fetch response shape for backward compatibility.
    Response uses: api_key, token_type, embedding_model, gpt_model, deploymentVersion, deploymentName,
    endpoint, companyId, tokenName (if present).
    """
    if not isinstance(data, dict):
        return data
    out = {}
    # api_key: decoded value from openaiToken or legacy api_key (caller already decoded openaiToken in place)
    out["api_key"] = data.get("openaiToken") or data.get("api_key") or ""
    # token_type: from tokenType or token_type; for response use "azureopenai" when vault has "azure"
    raw = (data.get("tokenType") or data.get("token_type") or "").strip().lower()
    out["token_type"] = "azureopenai" if raw == "azure" else (data.get("tokenType") or data.get("token_type") or "")
    # embedding_model: from embeddingsDeploymentName or embedding_model
    out["embedding_model"] = data.get("embeddingsDeploymentName") or data.get("embedding_model") or ""
    # gpt_model: from model or gpt_model
    out["gpt_model"] = data.get("model") or data.get("gpt_model") or ""
    # deploymentVersion: from apiVersion or deploymentVersion
    out["deploymentVersion"] = data.get("apiVersion") or data.get("deploymentVersion") or ""
    # Pass-through keys (unchanged)
    for key in ("companyId", "deploymentName", "endpoint", "tokenName"):
        if key in data and data[key] is not None:
            out[key] = data[key]
    return out
