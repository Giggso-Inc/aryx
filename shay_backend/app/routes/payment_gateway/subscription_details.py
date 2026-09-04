"""
POST /zoho/subscriptions/fetchCompanySubscriptionDetails   fetch_company_subscription_details
(mounted at /api/v1/payment-gateway)

Stated exception: kept as one large handler rather than split further — it
assembles a single CompanySubscriptionDetailsResponse from many independent
DB aggregates (user/admin counts, workspace count, channel count, AI response
count, storage sums, shared-inbox count, Zoho invoice fetch, usage-limit
parsing) that all feed the same `response_data` dict and the same
try/except envelope. Splitting any one aggregate out would require passing
`response_data` (or company_id/plan/subscription) across file boundaries for
no isolation benefit, since none of the aggregates are reused elsewhere.
"""

import json
import logging
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, status, Request, Depends
from sqlalchemy import select, func, join
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.middleware.auth_middleware import get_current_user_required
from app.models.company import Company
from app.models.subscription import Subscription
from app.models.subscription_plan import SubscriptionPlan
from app.models.user import User
from app.models.workspace import Workspace
from app.models.channel import Channel
from app.models.ai_response import AIResponse
from app.models.attachment import Attachment
from app.models.email_attachment import EmailAttachment
from app.models.app_account import AppAccount
from app.models.message import Message
from app.schemas.common import (
    SuccessResponse,
    CompanySubscriptionDetailsRequest,
    CompanySubscriptionDetailsResponse,
)
from app.services.zoho_service import get_zoho_service

from .helpers import (
    _is_missing_table_error,
    _parse_channel_limit_from_features,
    _parse_message_limit_from_features,
    _parse_storage_limit_from_features,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/zoho/subscriptions/fetchCompanySubscriptionDetails", response_model=SuccessResponse[CompanySubscriptionDetailsResponse])
async def fetch_company_subscription_details(
    request_data: CompanySubscriptionDetailsRequest,
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> SuccessResponse[CompanySubscriptionDetailsResponse]:
    """
    Fetch company subscription details.

    This endpoint returns comprehensive subscription information for a company,
    including plan details, user counts, channel counts, invoice details, etc.

    Only company admins can access this endpoint.
    """
    try:
        # Get current user for authentication
        user = await get_current_user_required(request)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unauthorized"
            )

        company_id = request_data.companyId

        # Verify user belongs to the requested company
        if str(user.company_id) != str(company_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User does not belong to the requested company"
            )

        # Verify user is admin
        if user.role != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only company admins can access subscription details"
            )

        # Get company
        company_result = await db.execute(
            select(Company).where(Company.id == company_id)
        )
        company = company_result.scalar_one_or_none()

        if not company:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Company not found"
            )

        # Get the active subscription for the company (filter by status = 'active')
        subscription_result = await db.execute(
            select(Subscription)
            .where(
                Subscription.company_id == company_id,
                Subscription.status == "active"
            )
            .order_by(Subscription.created_at.desc())
            .limit(1)
        )
        subscription = subscription_result.scalar_one_or_none()

        if not subscription:
            return SuccessResponse(
                success=False,
                data=None,
                message="No subscription found for company",
                code=status.HTTP_404_NOT_FOUND
            )

        # Get plan details
        plan_result = await db.execute(
            select(SubscriptionPlan).where(SubscriptionPlan.id == subscription.plan_id)
        )
        plan = plan_result.scalar_one_or_none()

        if not plan:
            return SuccessResponse(
                success=False,
                data=None,
                message="Plan not found",
                code=status.HTTP_404_NOT_FOUND
            )

        # Build response
        response_data = {
            "currentPlan": plan.name,
            "currentPlanCode": plan.plan_code,
            "planPeriod": plan.zoho_billing_cycle or f"{plan.interval} {plan.interval_unit}",
            "subscriptionId": subscription.zoho_subscription_id,
            "customerId": subscription.zoho_customer_id,
            "status": subscription.status,
            "currentPlanStatus": subscription.status,
            "currentCost": str(subscription.amount) if subscription.amount else None,
            "nextInvoiceDate": subscription.next_billing_date.isoformat() if subscription.next_billing_date else None,
            "expiresAt": subscription.current_period_end.isoformat() if subscription.current_period_end else None
        }

        # Get user info (admin count and user count)
        admin_count_result = await db.execute(
            select(func.count(User.id)).where(
                User.company_id == company_id,
                User.role == "admin"
            )
        )
        admin_count = admin_count_result.scalar() or 0

        user_count_result = await db.execute(
            select(func.count(User.id)).where(
                User.company_id == company_id,
                User.role != "admin"
            )
        )
        user_count = user_count_result.scalar() or 0

        response_data["userInfo"] = {
            "admin": admin_count,
            "users": user_count
        }

        # Get company group count (workspaces)
        workspace_count_result = await db.execute(
            select(func.count(Workspace.id)).where(Workspace.company_id == company_id)
        )
        workspace_count = workspace_count_result.scalar() or 0
        response_data["companyGroupCount"] = workspace_count

        # Get channel count
        channel_count_result = await db.execute(
            select(func.count(Channel.id)).where(Channel.company_id == company_id)
        )
        channel_count = channel_count_result.scalar() or 0
        response_data["companyChannelCount"] = channel_count

        # Get AI response count - count AI responses for company's workspaces
        workspace_ids_result = await db.execute(
            select(Workspace.id).where(Workspace.company_id == company_id)
        )
        workspace_ids = [w for w in workspace_ids_result.scalars().all()]

        ai_response_count = 0
        if workspace_ids:
            ai_response_count_result = await db.execute(
                select(func.count(AIResponse.id)).where(AIResponse.workspace_id.in_(workspace_ids))
            )
            ai_response_count = ai_response_count_result.scalar() or 0
        response_data["aiResponseCount"] = ai_response_count

        # Get storage count (sum of attachment sizes)
        # Sum from gg_attachments
        attachment_size_result = await db.execute(
            select(func.coalesce(func.sum(Attachment.file_size), 0)).where(
                Attachment.channel_id.in_(
                    select(Channel.id).where(Channel.company_id == company_id)
                )
            )
        )
        attachment_size = attachment_size_result.scalar() or 0

        # Sum from gg_email_attachments
        email_attachment_size_result = await db.execute(
            select(func.coalesce(func.sum(EmailAttachment.file_size), 0)).where(
                EmailAttachment.channel_id.in_(
                    select(Channel.id).where(Channel.company_id == company_id)
                )
            )
        )
        email_attachment_size = email_attachment_size_result.scalar() or 0

        total_storage = attachment_size + email_attachment_size
        response_data["storageCount"] = total_storage

        # Shared inbox count - count channels with email app accounts
        # Count distinct channels that have email app accounts (api_key = 'email')
        shared_inbox_result = await db.execute(
            select(func.count(func.distinct(Channel.id)))
            .select_from(join(Channel, AppAccount, Channel.id == AppAccount.channel_id))
            .where(
                Channel.company_id == company_id,
                AppAccount.api_key == 'email',
                AppAccount.is_active == True
            )
        )
        shared_inbox_count = shared_inbox_result.scalar() or 0
        response_data["sharedInboxCount"] = shared_inbox_count

        # Get metadata and addon details from subscription
        if subscription.usage_limits:
            if isinstance(subscription.usage_limits, dict):
                response_data["metadata"] = subscription.usage_limits
            elif isinstance(subscription.usage_limits, str):
                try:
                    response_data["metadata"] = json.loads(subscription.usage_limits)
                except:
                    response_data["metadata"] = None

        # Addon details - for now set to None (can be added later if stored)
        response_data["addonDetails"] = None

        # Fetch invoices from Zoho if customer_id exists
        invoice_details = []
        total_cost = 0.0

        if subscription.zoho_customer_id:
            try:
                # Get ALL subscriptions for the company to match invoices to their correct plans
                all_subscriptions_result = await db.execute(
                    select(Subscription)
                    .where(Subscription.company_id == company_id)
                    .order_by(Subscription.created_at.desc())
                )
                all_subscriptions = all_subscriptions_result.scalars().all()

                # Create a mapping of subscription_id -> plan for quick lookup
                subscription_plans_map = {}
                for sub in all_subscriptions:
                    plan_result = await db.execute(
                        select(SubscriptionPlan).where(SubscriptionPlan.id == sub.plan_id)
                    )
                    sub_plan = plan_result.scalar_one_or_none()
                    if sub_plan:
                        subscription_plans_map[sub.id] = {
                            "subscription": sub,
                            "plan": sub_plan
                        }

                # Determine platform_name from subscription or use default
                # Default to 'prism7' to match the individual invoice endpoint behavior
                # If needed, we can add platform_name to subscription model later
                zoho_service_instance = get_zoho_service('prism7')
                invoices = await zoho_service_instance.get_customer_invoices(subscription.zoho_customer_id)

                if invoices:
                    for invoice in invoices:
                        invoice_id = invoice.get("invoice_id")
                        invoice_date_str = invoice.get("invoice_date")

                        # Fetch full invoice details from Zoho API to get invoice_items with name, code, and subscription_id
                        full_invoice_data = None
                        invoice_name = None
                        invoice_code = None
                        zoho_subscription_id = None

                        try:
                            # Call the individual invoice retrieval API to get full details
                            full_invoice_data = await zoho_service_instance.get_invoice(invoice_id)

                            # Extract subscription_id, name, and code from invoice response
                            # subscription_id can be in invoice_items[0].subscription_id OR subscriptions[0].subscription_id
                            invoice_items = full_invoice_data.get("invoice_items", [])
                            if invoice_items and len(invoice_items) > 0:
                                # Get name, code, and subscription_id from the first invoice item
                                first_item = invoice_items[0]
                                invoice_name = first_item.get("name")
                                invoice_code = first_item.get("code")
                                zoho_subscription_id = first_item.get("subscription_id")

                            # If subscription_id not found in invoice_items, check subscriptions array
                            if not zoho_subscription_id and full_invoice_data.get("subscriptions"):
                                subscriptions = full_invoice_data.get("subscriptions", [])
                                if subscriptions and len(subscriptions) > 0:
                                    zoho_subscription_id = subscriptions[0].get("subscription_id")

                            logger.info(f"✅ Extracted invoice details - invoice_id: {invoice_id}, subscription_id: {zoho_subscription_id}, name: {invoice_name}, code: {invoice_code}")
                        except Exception as detail_error:
                            logger.warning(f"⚠️ Could not fetch full invoice details for {invoice_id}: {detail_error}")
                            # Continue with basic invoice data if detailed fetch fails

                        # Use full invoice data if available, otherwise use basic invoice data
                        invoice_to_process = full_invoice_data if full_invoice_data else invoice

                        # Build subscription plan details object
                        # Use name and code directly from invoice_items (from Zoho API)
                        # If not available, use current plan as fallback
                        subscription_plan_details = {
                            "name": invoice_name if invoice_name else plan.name,
                            "planCode": invoice_code if invoice_code else plan.plan_code
                        }

                        # Use invoice data from full invoice if available, otherwise use basic invoice
                        invoice_data = {
                            "invoice_id": invoice_id,
                            "number": invoice_to_process.get("number") or invoice_to_process.get("invoice_number"),
                            "status": invoice_to_process.get("status"),
                            "invoice_date": invoice_to_process.get("invoice_date") or invoice_to_process.get("date"),
                            "due_date": invoice_to_process.get("due_date"),
                            "total": invoice_to_process.get("total"),
                            "balance": invoice_to_process.get("balance"),
                            "payment_made": invoice_to_process.get("payment_made"),
                            "currency_code": invoice_to_process.get("currency_code"),
                            "currency_symbol": invoice_to_process.get("currency_symbol"),
                            "subscriptionPlan": subscription_plan_details
                        }

                        invoice_details.append(invoice_data)

                        # Calculate total cost from paid invoices
                        invoice_status = invoice_to_process.get("status")
                        if invoice_status == "paid":
                            invoice_total = invoice_to_process.get("total", 0)
                            if isinstance(invoice_total, (int, float)):
                                total_cost += float(invoice_total)
                            elif isinstance(invoice_total, str):
                                try:
                                    total_cost += float(invoice_total)
                                except:
                                    pass

                logger.info(f"Fetched {len(invoice_details)} invoices for customer {subscription.zoho_customer_id}")
            except Exception as invoice_error:
                logger.warning(f"Could not fetch invoices from Zoho: {invoice_error}")

        response_data["invoiceDetails"] = invoice_details
        response_data["totalCost"] = str(total_cost) if total_cost > 0 else None

        # Calculate usage statistics
        # Use the same parsing functions as the validation API for consistency
        try:
            # Parse limits from plan features using the same functions as validation API
            channel_limit = _parse_channel_limit_from_features(plan.features)
            message_limit_per_channel = _parse_message_limit_from_features(plan.features)
            storage_limit_bytes_per_channel = _parse_storage_limit_from_features(plan.features)

            # Message and storage limits are per channel, so multiply by channel limit for total
            message_limit = message_limit_per_channel * channel_limit if channel_limit > 0 and message_limit_per_channel > 0 else 0
            storage_limit_bytes = storage_limit_bytes_per_channel * channel_limit if channel_limit > 0 and storage_limit_bytes_per_channel > 0 else 0

            # Get current usage - channels (already calculated above)
            current_channels = channel_count

            # Get current usage - messages (count messages for company's channels)
            # Messages are directly linked to channels, and channels are linked to company
            message_count_result = await db.execute(
                select(func.count(Message.id)).where(
                    Message.channel_id.in_(
                        select(Channel.id).where(Channel.company_id == company_id)
                    )
                )
            )
            current_messages = message_count_result.scalar() or 0

            # Get current usage - storage (already calculated above as total_storage in bytes)
            current_storage_bytes = total_storage

            # Calculate available amounts
            channel_available = max(0, channel_limit - current_channels) if channel_limit > 0 else 0
            message_available = max(0, message_limit - current_messages) if message_limit > 0 else 0
            storage_available_bytes = max(0, storage_limit_bytes - current_storage_bytes) if storage_limit_bytes > 0 else 0

            # Build usage statistics object
            response_data["usageStatistics"] = {
                "channelLimit": channel_limit,
                "messageLimit": message_limit,
                "StorageLimit": storage_limit_bytes,
                "channelavailable": channel_available,
                "messageavailable": message_available,
                "Storageavailable": storage_available_bytes
            }
        except Exception as usage_error:
            # If there's an error calculating usage statistics, set defaults
            logger.warning(f"Error calculating usage statistics: {usage_error}")
            response_data["usageStatistics"] = {
                "channelLimit": 0,
                "messageLimit": 0,
                "StorageLimit": 0,
                "channelavailable": 0,
                "messageavailable": 0,
                "Storageavailable": 0
            }

        validated_response = CompanySubscriptionDetailsResponse(**response_data)

        return SuccessResponse(
            success=True,
            data=validated_response,
            message="Subscription details fetched successfully",
            code=status.HTTP_200_OK
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Exception at fetch company subscription details: %s", str(e))
        # Previous flow unchanged: only missing-table errors get generic message; all other errors keep str(e)
        detail = "Internal Server Error: Try Again Later" if _is_missing_table_error(e) else f"Internal server error: {str(e)}"
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=detail
        )
