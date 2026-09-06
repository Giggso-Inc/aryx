"""
process_ai_request — background task helper for POST /trigger/{message_id}.

Split out of app/routes/agent/trigger.py (itself split from the original
370-line app/routes/agent.py) to keep both files under the Raven 150-line
style limit — see docs/RAVEN_STYLE_COMPLIANCE_PLAN_2026-09-03.md, wave B5.
"""

import asyncio
from datetime import datetime

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.message import Message
from app.models.ai_response import AIResponse


async def process_ai_request(message_id: str) -> None:
    """Process AI request (simulated)"""
    # Create new session for background task
    async with AsyncSessionLocal() as db:
        try:
            # Get message and AI response
            stmt = select(Message).where(Message.id == message_id)
            result = await db.execute(stmt)
            message = result.scalar_one_or_none()

            if not message:
                return

            stmt = select(AIResponse).where(AIResponse.message_id == message_id)
            result = await db.execute(stmt)
            ai_response = result.scalar_one_or_none()

            if not ai_response:
                return

            # Close session before long operation
            await db.close()

            # Simulate AI processing
            await asyncio.sleep(2)  # Simulate processing time

            # Create new session for final operations
            async with AsyncSessionLocal() as db:
                stmt = select(Message).where(Message.id == message_id)
                result = await db.execute(stmt)
                message = result.scalar_one_or_none()

                if not message:
                    return

                stmt = select(AIResponse).where(AIResponse.message_id == message_id)
                result = await db.execute(stmt)
                ai_response = result.scalar_one_or_none()

                if not ai_response:
                    return

                # Update AI response with simulated result
                ai_response.status = "completed"
                ai_response.response_content = f"AI analysis of: {message.content[:100]}..."
                ai_response.confidence_score = 0.85
                ai_response.relevance_score = 0.90
                ai_response.processing_time_ms = 2000
                ai_response.processed_at = datetime.utcnow()

                # Update message
                message.is_ai_processed = True
                message.ai_provider = ai_response.ai_provider
                message.ai_model = ai_response.ai_model
                message.ai_processing_time = ai_response.processing_time_ms

                await db.commit()

        except Exception as e:
            print(f"Error processing AI request: {e}")
            # Create new session for error handling
            async with AsyncSessionLocal() as db:
                stmt = select(AIResponse).where(AIResponse.message_id == message_id)
                result = await db.execute(stmt)
                ai_response = result.scalar_one_or_none()

                if ai_response:
                    ai_response.status = "failed"
                    ai_response.error_message = str(e)
                    await db.commit()
