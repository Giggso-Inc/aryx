"""
AI Agent routes for webhook callbacks and AI processing management
"""

import httpx
from datetime import datetime
from typing import Dict, Any
from fastapi import APIRouter, HTTPException, status, Request, Depends, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.database import get_db, AsyncSessionLocal
from app.core.auth import generate_ai_response_id
from app.core.config import settings
from app.models.message import Message
from app.models.ai_response import AIResponse
from app.schemas.agent import (
    AICallback,
    AIStatus,
    AIHealth,
    AIStats,
    AITrigger,
    AIWebhookPayload
)

router = APIRouter()


@router.post("/callback")
async def ai_callback(
    callback_data: AICallback,
    db: AsyncSession = Depends(get_db)
):
    """Receive AI processing callback"""
    try:
        # Get message
        stmt = select(Message).where(Message.id == callback_data.message_id)
        result = await db.execute(stmt)
        message = result.scalar_one_or_none()
        
        if not message:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Message not found"
            )
        
        # Get or create AI response
        stmt = select(AIResponse).where(AIResponse.message_id == callback_data.message_id)
        result = await db.execute(stmt)
        ai_response = result.scalar_one_or_none()
        
        if not ai_response:
            ai_response = AIResponse(
                id=generate_ai_response_id(),
                message_id=callback_data.message_id,
                thread_id=callback_data.thread_id,
                workspace_id=callback_data.workspace_id,
                ai_provider=callback_data.ai_provider,
                ai_model=callback_data.ai_model,
                response_content=callback_data.response_content,
                response_type=callback_data.response_type,
                confidence_score=callback_data.confidence_score,
                relevance_score=callback_data.relevance_score,
                processing_time_ms=callback_data.processing_time_ms,
                status=callback_data.status,
                error_message=callback_data.error_message,
                metadata=callback_data.metadata,
                tags=callback_data.tags,
                processed_at=datetime.utcnow() if callback_data.status == "completed" else None
            )
            db.add(ai_response)
        else:
            # Update existing AI response
            ai_response.response_content = callback_data.response_content
            ai_response.response_type = callback_data.response_type
            ai_response.confidence_score = callback_data.confidence_score
            ai_response.relevance_score = callback_data.relevance_score
            ai_response.processing_time_ms = callback_data.processing_time_ms
            ai_response.status = callback_data.status
            ai_response.error_message = callback_data.error_message
            ai_response.metadata = callback_data.metadata
            ai_response.tags = callback_data.tags
            ai_response.processed_at = datetime.utcnow() if callback_data.status == "completed" else None
        
        # Update message with AI processing info
        message.is_ai_processed = True
        message.ai_provider = callback_data.ai_provider
        message.ai_model = callback_data.ai_model
        message.ai_processing_time = callback_data.processing_time_ms
        
        await db.commit()
        
        return {"message": "AI callback processed successfully"}
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process AI callback: {str(e)}"
        )


@router.post("/status")
async def ai_status_update(
    status_data: AIStatus,
    db: AsyncSession = Depends(get_db)
):
    """Receive AI processing status update"""
    try:
        # Get AI response
        stmt = select(AIResponse).where(AIResponse.message_id == status_data.message_id)
        result = await db.execute(stmt)
        ai_response = result.scalar_one_or_none()
        
        if not ai_response:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="AI response not found"
            )
        
        # Update status
        ai_response.status = status_data.status
        ai_response.error_message = status_data.error_message
        ai_response.metadata = status_data.metadata
        
        await db.commit()
        
        return {"message": "AI status updated successfully"}
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update AI status: {str(e)}"
        )


@router.get("/health", response_model=AIHealth)
async def ai_health_check():
    """Check AI agent health"""
    try:
        # Simple health check - in a real implementation, you might check actual AI services
        return AIHealth(
            status="healthy",
            provider="openai",
            model="gpt-4",
            response_time_ms=100,
            last_check=datetime.utcnow(),
            error_count=0,
            success_rate=0.95
        )
    except Exception as e:
        return AIHealth(
            status="unhealthy",
            provider="unknown",
            model="unknown",
            last_check=datetime.utcnow(),
            error_count=1,
            success_rate=0.0
        )


@router.get("/stats", response_model=AIStats)
async def ai_stats(db: AsyncSession = Depends(get_db)):
    """Get AI processing statistics"""
    try:
        # Get total requests
        total_query = select(func.count(AIResponse.id))
        total_result = await db.execute(total_query)
        total_requests = total_result.scalar()
        
        # Get successful requests
        success_query = select(func.count(AIResponse.id)).where(AIResponse.status == "completed")
        success_result = await db.execute(success_query)
        successful_requests = success_result.scalar()
        
        # Get failed requests
        failed_query = select(func.count(AIResponse.id)).where(AIResponse.status == "failed")
        failed_result = await db.execute(failed_query)
        failed_requests = failed_result.scalar()
        
        # Get average response time
        time_query = select(func.avg(AIResponse.processing_time_ms)).where(AIResponse.processing_time_ms.isnot(None))
        time_result = await db.execute(time_query)
        avg_response_time = time_result.scalar() or 0
        
        # Get total processing time
        total_time_query = select(func.sum(AIResponse.processing_time_ms)).where(AIResponse.processing_time_ms.isnot(None))
        total_time_result = await db.execute(total_time_query)
        total_processing_time = total_time_result.scalar() or 0
        
        # Get requests by time period (simplified)
        today_query = select(func.count(AIResponse.id)).where(
            AIResponse.created_at >= datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        )
        today_result = await db.execute(today_query)
        requests_today = today_result.scalar()
        
        # Get top providers
        provider_query = select(
            AIResponse.ai_provider,
            func.count(AIResponse.id).label('count')
        ).group_by(AIResponse.ai_provider).order_by(func.count(AIResponse.id).desc()).limit(5)
        provider_result = await db.execute(provider_query)
        top_providers = [{"provider": row.ai_provider, "count": row.count} for row in provider_result]
        
        # Get top models
        model_query = select(
            AIResponse.ai_model,
            func.count(AIResponse.id).label('count')
        ).group_by(AIResponse.ai_model).order_by(func.count(AIResponse.id).desc()).limit(5)
        model_result = await db.execute(model_query)
        top_models = [{"model": row.ai_model, "count": row.count} for row in model_result]
        
        return AIStats(
            total_requests=total_requests,
            successful_requests=successful_requests,
            failed_requests=failed_requests,
            average_response_time_ms=float(avg_response_time),
            total_processing_time_ms=int(total_processing_time),
            requests_today=requests_today,
            requests_this_week=requests_today,  # Simplified
            requests_this_month=requests_today,  # Simplified
            top_providers=top_providers,
            top_models=top_models
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get AI stats: {str(e)}"
        )


@router.post("/trigger/{message_id}")
async def trigger_ai_processing(
    message_id: str,
    trigger_data: AITrigger,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db)
):
    """Manually trigger AI processing for a message"""
    try:
        # Get message
        stmt = select(Message).where(Message.id == message_id)
        result = await db.execute(stmt)
        message = result.scalar_one_or_none()
        
        if not message:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Message not found"
            )
        
        # Check if AI response already exists
        stmt = select(AIResponse).where(AIResponse.message_id == message_id)
        result = await db.execute(stmt)
        ai_response = result.scalar_one_or_none()
        
        if ai_response and not trigger_data.force_retry:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="AI processing already triggered for this message"
            )
        
        # Create or update AI response
        if not ai_response:
            ai_response = AIResponse(
                id=generate_ai_response_id(),
                message_id=message_id,
                thread_id=message.thread_id,
                workspace_id=message.workspace_id,
                ai_provider=trigger_data.ai_provider or "openai",
                ai_model=trigger_data.ai_model or "gpt-4",
                response_content="",
                status="pending"
            )
            db.add(ai_response)
        else:
            # Reset for retry
            ai_response.status = "pending"
            ai_response.error_message = None
            ai_response.retry_count += 1
            if trigger_data.ai_provider:
                ai_response.ai_provider = trigger_data.ai_provider
            if trigger_data.ai_model:
                ai_response.ai_model = trigger_data.ai_model
        
        await db.commit()
        
        # Trigger AI processing
        background_tasks.add_task(process_ai_request, message_id)
        
        return {"message": "AI processing triggered successfully"}
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to trigger AI processing: {str(e)}"
        )


async def process_ai_request(message_id: str):
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
            import asyncio
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