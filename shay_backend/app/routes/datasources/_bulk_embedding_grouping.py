"""
Grouping helpers for _bulk_embedding_dispatch.trigger_bulk_embeddings.

Private module: split out of the dispatch logic purely to keep each file
under the line cap.
"""

from typing import Any, Dict, List


def build_vault_id_mapping(embedding_required_datasources: List[Dict[str, Any]], vault_records) -> Dict[str, Any]:
    """Map giggso_vault_id (str) -> vault_unique_id for every embedding-required datasource."""
    vault_id_mapping = {}
    for ds in embedding_required_datasources:
        giggso_vault_id = ds.get("giggso_vault_id")
        if giggso_vault_id:
            for record in vault_records:
                # Convert both to strings for comparison to handle UUID vs string mismatches
                if str(record.giggso_vault_id) == str(giggso_vault_id):
                    vault_id_mapping[str(giggso_vault_id)] = record.vault_unique_id
                    break
    return vault_id_mapping


def group_by_embedd_type(embedding_required_datasources: List[Dict[str, Any]]):
    """Split embedding-required datasources into (textual, tabular) buckets."""
    from app.services.ml_service import get_embedd_type_from_file_type

    textual_datasources = []
    tabular_datasources = []
    for ds in embedding_required_datasources:
        embedd_type = get_embedd_type_from_file_type(
            file_type=ds.get("file_type"),
            storage_type=ds.get("storage_type"),
            provider=ds.get("provider")
        )
        base_type = embedd_type.split("_")[0]
        target = tabular_datasources if base_type == "tabular" else textual_datasources
        target.append({"datasource": ds, "giggso_vault_id": ds.get("giggso_vault_id"), "embedd_type": embedd_type})
    return textual_datasources, tabular_datasources
