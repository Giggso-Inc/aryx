"""OpenAI vault-token lookup for the ML embedding API."""

import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.giggso_vault import GiggsoVault


async def get_openai_vault_token_for_company(db: AsyncSession, company_id: str) -> Optional[str]:
    """
    Fetch vault_unique_id from gg_vault for the company and vault_type='gpt_token'.
    Used as openaiVaultToken when calling the ML API (/shay/email/embeddings).
    """
    try:
        company_uuid = uuid.UUID(company_id) if isinstance(company_id, str) else company_id
    except (ValueError, TypeError):
        return None
    stmt = (
        select(GiggsoVault.vault_unique_id)
        .where(
            GiggsoVault.company_id == company_uuid,
            GiggsoVault.vault_type == "gpt_token",
        )
        .order_by(GiggsoVault.created_datetime.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    return row if row else None
