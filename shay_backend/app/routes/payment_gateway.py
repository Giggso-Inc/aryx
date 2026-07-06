"""
Payment Gateway routes for Zoho integration.

This module handles payment processing and subscription management through Zoho,
including hosted payment page creation and subscription management.

Author: Karthick Chandrasekar
Date: 2025-08-26
Version: 1.0.0
"""

from typing import Optional, Dict, Any, List
from fastapi import APIRouter, HTTPException, status, Request, Depends, Query, Body
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, func, join
from datetime import datetime, timedelta
from decimal import Decimal
import uuid
import httpx
import json
import logging
import re

from app.core.database import get_db
from app.core.config import settings
from app.middleware.auth_middleware import get_current_user_required
from app.models.user import User
from app.models.company import Company
from app.models.subscription_plan import SubscriptionPlan
from app.models.subscription import Subscription
from app.models.channel import Channel
from app.models.message import Message
from app.models.attachment import Attachment
from app.models.email_attachment import EmailAttachment
from app.models.datasource import Datasource
from app.models.workspace import Workspace
from app.models.ai_response import AIResponse
from app.models.app_account import AppAccount
from app.schemas.common import SuccessResponse, ZohoHostedPageRequest, ZohoHostedPageResponse, SubscriptionUpdateRequest, SubscriptionCancelRequest, SubscriptionReactivateRequest, ValidatePaymentRequest, SubscriptionValidationRequest, SubscriptionCreateRequest, CompanySubscriptionDetailsRequest, CompanySubscriptionDetailsResponse, CompanyInvoiceDetailsResponse
from app.schemas.subscription_plan import SubscriptionPlanNodeResponse
from app.services.zoho_service import zoho_service, get_zoho_service

logger = logging.getLogger(__name__)

router = APIRouter()


def _is_missing_table_error(exc: Exception) -> bool:
    """True if any table used by the API is missing. Used only in the exception handler; success path is unchanged."""
    msg = str(exc).lower()
    return "does not exist" in msg or "undefinedtableerror" in msg


def _is_valid_uuid(value: str) -> bool:
    """Return True if value is a valid UUID string (32–36 chars, valid hex/hyphens)."""
    if not value or not isinstance(value, str):
        return False
    try:
        uuid.UUID(value)
        return True
    except (ValueError, TypeError):
        return False


async def _fetch_invoice_details_for_company(db: AsyncSession, company_id: str) -> tuple:
    """
    Fetch invoice details from Zoho for the company's active subscription.
    Returns (invoice_details: list, total_cost: float). Uses same structure as fetchCompanySubscriptionDetails.
    company_id can be str or UUID; DB comparison accepts both.
    """
    invoice_details = []
    total_cost = 0.0
    # Get active subscription for company
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
    if not subscription or not subscription.zoho_customer_id:
        return invoice_details, total_cost
    # Get plan for fallback name/code
    plan_result = await db.execute(
        select(SubscriptionPlan).where(SubscriptionPlan.id == subscription.plan_id)
    )
    plan = plan_result.scalar_one_or_none()
    plan_name = plan.name if plan else None
    plan_code = plan.plan_code if plan else None
    try:
        zoho_service_instance = get_zoho_service("prism7")
        invoices = await zoho_service_instance.get_customer_invoices(subscription.zoho_customer_id)
        if not invoices:
            return invoice_details, total_cost
        for invoice in invoices:
            invoice_id = invoice.get("invoice_id")
            full_invoice_data = None
            invoice_name = None
            invoice_code = None
            try:
                full_invoice_data = await zoho_service_instance.get_invoice(invoice_id)
                invoice_items = full_invoice_data.get("invoice_items", [])
                if invoice_items:
                    first_item = invoice_items[0]
                    invoice_name = first_item.get("name")
                    invoice_code = first_item.get("code")
            except Exception as detail_error:
                logger.warning("Could not fetch full invoice details for %s: %s", invoice_id, detail_error)
            invoice_to_process = full_invoice_data if full_invoice_data else invoice
            subscription_plan_details = {
                "name": invoice_name if invoice_name else plan_name,
                "planCode": invoice_code if invoice_code else plan_code
            }
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
            if invoice_to_process.get("status") == "paid":
                invoice_total = invoice_to_process.get("total", 0)
                if isinstance(invoice_total, (int, float)):
                    total_cost += float(invoice_total)
                elif isinstance(invoice_total, str):
                    try:
                        total_cost += float(invoice_total)
                    except (ValueError, TypeError):
                        pass
    except Exception as invoice_error:
        logger.warning("Could not fetch invoices from Zoho for company %s: %s", company_id, invoice_error)
    return invoice_details, total_cost


def parse_features_to_limits(features: Any) -> Dict[str, int]:
    """
    Parse features from subscription plan to extract limits.
    
    Features can be in format like: ["5 Channels", "10 Messages", "5GB Storage"]
    Returns a dictionary with channelLimit, messageLimit, and StorageLimit.
    """
    limits = {
        "channelLimit": 0,
        "messageLimit": 0,
        "StorageLimit": 0
    }
    
    if not features:
        return limits
    
    # Handle list format: ["5 Channels", "10 Messages", "5GB Storage"]
    features_list = []
    if isinstance(features, list):
        features_list = features
    elif isinstance(features, dict):
        # If it's a dict, extract values
        features_list = list(features.values())
    elif isinstance(features, str):
        # If it's a string, try to parse as JSON
        try:
            parsed = json.loads(features)
            if isinstance(parsed, list):
                features_list = parsed
            elif isinstance(parsed, dict):
                features_list = list(parsed.values())
        except:
            features_list = [features]
    
    # Parse each feature string
    for feature in features_list:
        if not isinstance(feature, str):
            continue
        
        feature_lower = feature.lower()
        
        # Extract number and unit
        # Pattern: "5 Channels", "10 Messages", "5GB Storage", "5 GB Storage"
        # Try pattern with storage unit first (GB, MB, KB): "5GB Storage" or "5 GB Storage"
        match = re.search(r'(\d+(?:\.\d+)?)\s*([kmg]b)\s*(channel|message|storage)', feature_lower)
        if match:
            number = float(match.group(1))
            unit = match.group(2).lower()
            feature_type = match.group(3)
        else:
            # Try pattern without unit: "5 Channels", "10 Messages"
            match = re.search(r'(\d+(?:\.\d+)?)\s+(channel|message|storage)', feature_lower)
            if match:
                number = float(match.group(1))
                unit = ""
                feature_type = match.group(2)
            else:
                continue
        
        # Convert to base units
        if feature_type == "channel":
            limits["channelLimit"] = int(number)
        elif feature_type == "message":
            limits["messageLimit"] = int(number)
        elif feature_type == "storage":
            # Convert storage to bytes (GB -> bytes)
            if unit == "gb":
                limits["StorageLimit"] = int(number * 1024 * 1024 * 1024)  # GB to bytes
            elif unit == "mb":
                limits["StorageLimit"] = int(number * 1024 * 1024)  # MB to bytes
            elif unit == "kb":
                limits["StorageLimit"] = int(number * 1024)  # KB to bytes
            else:
                # Assume bytes if no unit
                limits["StorageLimit"] = int(number)
    
    return limits


def extract_price_from_brackets(addon: Dict[str, Any]) -> Optional[float]:
    """
    Extract price from price_brackets array.
    
    Zoho API returns price in price_brackets format, not as a direct price field.
    This helper extracts the price from the first price bracket.
    
    Args:
        addon: Addon data dictionary from Zoho API
        
    Returns:
        Price as float, or None if not found
    """
    price_brackets = addon.get('price_brackets', [])
    if price_brackets and len(price_brackets) > 0:
        # Get the first price bracket's price
        first_bracket = price_brackets[0]
        if isinstance(first_bracket, dict) and 'price' in first_bracket:
            try:
                return float(first_bracket.get('price', 0))
            except (ValueError, TypeError):
                pass
    # Fallback to direct price field if available
    price = addon.get('price')
    if price is not None:
        try:
            return float(price)
        except (ValueError, TypeError):
            pass
    return None


@router.post("/zoho/subscriptions/hostedPage/create", response_model=SuccessResponse[ZohoHostedPageResponse])
async def create_zoho_hosted_page(
    request_data: ZohoHostedPageRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Creates a Zoho hosted payment page for subscription.
    
    This endpoint uses real Zoho API integration.
    """
    try:
        # Extract plan information from request
        plan_name = request_data.plan.get("name")
        plan_code = request_data.plan.get("planCode")
        
        # Find the plan in database
        plan_result = await db.execute(
            select(SubscriptionPlan).where(
                SubscriptionPlan.name == plan_name,
                SubscriptionPlan.plan_code == plan_code,
                SubscriptionPlan.is_active == True
            )
        )
        plan = plan_result.scalar_one_or_none()
        
        if not plan:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Plan not found"
            )
        
        # Extract customer information
        customer_data = request_data.customer
        company_name = customer_data.get("companyName")
        customer_email = customer_data.get("email")
        
        # Find the company
        company_result = await db.execute(
            select(Company).where(Company.name == company_name)
        )
        company = company_result.scalar_one_or_none()
        
        if not company:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Company not found"
            )
        
        # Check for existing Zoho customer ID on company's latest subscription (use existing customer in Zoho when present)
        subscription_result = await db.execute(
            select(Subscription)
            .where(Subscription.company_id == company.id)
            .order_by(Subscription.created_at.desc())
            .limit(1)
        )
        existing_subscription = subscription_result.scalar_one_or_none()
        zoho_customer_id = existing_subscription.zoho_customer_id if existing_subscription else None
        
        # Create hosted page using Zoho service
        try:
            # Get platform_name from request (if provided)
            platform_name = request_data.platform_name if hasattr(request_data, 'platform_name') else None
            
            # Get appropriate Zoho service instance based on platform_name
            zoho_service_instance = get_zoho_service(platform_name)
            
            # Prepare subscription data: send zoho_customer_id when we have it (existing customer), else customer object for new customer
            subscription_data = {
                "planName": plan.name,
                "planCode": plan.plan_code,
                "planDescription": plan.description,
                "redirectUrl": request_data.redirectUrl,
                "autoCollect": getattr(request_data, "autoCollect", True),
            }
            if zoho_customer_id:
                subscription_data["zoho_customer_id"] = zoho_customer_id
            else:
                subscription_data["customerName"] = customer_data.get("displayName", customer_data.get("companyName", "Customer"))
                subscription_data["customerEmail"] = customer_data.get("email")
                subscription_data["companyName"] = customer_data.get("companyName")
                subscription_data["companyDomain"] = customer_data.get("website", "")
            
            zoho_response = await zoho_service_instance.create_hosted_page(subscription_data)
            
            # Extract hosted page details from Zoho response
            hosted_page_id = zoho_response.get("hostedPageId")
            hosted_page_url = zoho_response.get("hostedPageUrl")
            
            if not hosted_page_id or not hosted_page_url:
                raise Exception("Invalid response from Zoho API")
            
            # Create hosted page data
            hosted_page_data = ZohoHostedPageResponse(
                hostedPageId=hosted_page_id,
                url=hosted_page_url,
                planId=str(plan.id),
                planName=plan.name,
                amount=float(plan.monthly_price),
                companyId=str(company.id),
                companyName=company.name,
                expiresAt=(datetime.utcnow() + timedelta(hours=24)).isoformat()
            )
            
            return SuccessResponse(
                success=True,
                data=hosted_page_data,
                message="Zoho hosted payment page created successfully",
                code=status.HTTP_200_OK
            )
            
        except Exception as zoho_error:
            # Fallback to mock response if Zoho API fails
            print(f"Zoho API error: {zoho_error}")
            hosted_page_id = str(uuid.uuid4())
            
            # Use appropriate base URL; no platform_name or unknown value → default (previous flow unchanged)
            if platform_name:
                pn = platform_name.lower()
                if pn == "prism7":
                    base_url = settings.PRISM_ZOHO_BASE_URL
                elif pn == "accsell":
                    base_url = settings.SHAY_ZOHO_BASE_URL
                elif pn == "zaptag":
                    base_url = settings.ZAPTAG_ZOHO_BASE_URL
                else:
                    base_url = settings.ZOHO_BASE_URL
            else:
                base_url = settings.ZOHO_BASE_URL
            
            hosted_page_data = ZohoHostedPageResponse(
                hostedPageId=hosted_page_id,
                url=f"{base_url}/hosted-page/{hosted_page_id}",
                planId=str(plan.id),
                planName=plan.name,
                amount=float(plan.monthly_price),
                companyId=str(company.id),
                companyName=company.name,
                expiresAt=(datetime.utcnow() + timedelta(hours=24)).isoformat()
            )
            
            return SuccessResponse(
                success=True,
                data=hosted_page_data,
                message="Hosted payment page created (fallback mode)",
                code=status.HTTP_200_OK
            )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create hosted page: {str(e)}"
        )


@router.post("/zoho/subscriptions/create", response_model=SuccessResponse[dict])
async def create_zoho_subscription(
    subscription_request: SubscriptionCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Create a subscription in Zoho and save to local database.
    
    This endpoint creates a subscription in Zoho first, then saves the subscription
    details to the local database with the Zoho subscription_id.
    
    Reference: https://www.zoho.com/billing/api/v1/subscription/#create-a-subscription
    """
    try:
        # Validate request
        if not subscription_request:
            return SuccessResponse(
                success=False,
                data=None,
                message="Subscription request is required",
                code=status.HTTP_400_BAD_REQUEST
            )
        
        # Get current user for authentication
        user = await get_current_user_required(request)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unauthorized"
            )
        
        # Get company
        company_result = await db.execute(
            select(Company).where(Company.id == user.company_id)
        )
        company = company_result.scalar_one_or_none()
        
        if not company:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Company not found"
            )
        
        platform_name = subscription_request.platform_name
        zoho_service_instance = get_zoho_service(platform_name)
        
        # Convert Pydantic model to dict for Zoho service
        subscription_data = subscription_request.model_dump(exclude_none=True)
        
        # Call Zoho API to create subscription
        try:
            zoho_response = await zoho_service_instance.create_subscription(subscription_data)
            
            if not zoho_response or not zoho_response.get('subscription'):
                return SuccessResponse(
                    success=False,
                    data=None,
                    message="Failed to create subscription in Zoho",
                    code=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
            
            # Extract subscription data from Zoho response
            zoho_subscription = zoho_response.get('subscription', {})
            zoho_subscription_id = zoho_subscription.get('subscription_id')
            
            # Extract customer_id - can be in customer object or directly in subscription
            zoho_customer_id = None
            if zoho_subscription.get('customer'):
                if isinstance(zoho_subscription['customer'], dict):
                    zoho_customer_id = zoho_subscription['customer'].get('customer_id')
                else:
                    zoho_customer_id = zoho_subscription['customer']
            elif zoho_subscription.get('customer_id'):
                zoho_customer_id = zoho_subscription.get('customer_id')
            
            if not zoho_subscription_id:
                return SuccessResponse(
                    success=False,
                    data=None,
                    message="Zoho subscription ID not found in response",
                    code=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
            
            # Get plan details from Zoho response or local database
            zoho_plan = zoho_subscription.get('plan', {})
            plan_code = zoho_plan.get('plan_code')
            plan_name = zoho_plan.get('name')
            
            # Try to find local plan by plan_code (required for local subscription)
            plan = None
            if plan_code:
                plan_result = await db.execute(
                    select(SubscriptionPlan).where(SubscriptionPlan.plan_code == plan_code)
                )
                plan = plan_result.scalar_one_or_none()
                if not plan:
                    logger.warning(f"Plan with code {plan_code} not found in local database")
                    # Plan must exist locally to create subscription (plan_id is required in DB)
                    return SuccessResponse(
                        success=False,
                        data=None,
                        message=f"Plan with code {plan_code} not found in local database. Please ensure the plan exists before creating subscription.",
                        code=status.HTTP_400_BAD_REQUEST
                    )
            
            # Parse dates from Zoho response
            created_time_str = zoho_subscription.get('created_time')
            next_billing_at_str = zoho_subscription.get('next_billing_at')
            expires_at_str = zoho_subscription.get('expires_at')
            
            created_time = datetime.utcnow()
            if created_time_str:
                try:
                    # Parse ISO format: "2016-06-11T17:57:13-0700" or "2016-06-11"
                    match = re.match(r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})', created_time_str)
                    if match:
                        created_time = datetime.strptime(match.group(1), "%Y-%m-%dT%H:%M:%S")
                    else:
                        created_time = datetime.strptime(created_time_str.split('T')[0], "%Y-%m-%d")
                except Exception as date_error:
                    logger.warning(f"Could not parse created_time: {date_error}")
                    created_time = datetime.utcnow()
            
            next_billing_date = None
            if next_billing_at_str:
                try:
                    next_billing_date = datetime.strptime(next_billing_at_str, "%Y-%m-%d")
                except Exception as date_error:
                    logger.warning(f"Could not parse next_billing_at: {date_error}")
            
            # Note: expires_at is stored as string in Java code, but we'll parse it if needed
            # For now, we'll store it in usage_limits or skip if not critical
            
            # Determine billing cycle and period end
            interval = zoho_subscription.get('interval', 1)
            interval_unit = zoho_subscription.get('interval_unit', 'months')
            billing_cycle = f"{interval} {interval_unit}"
            
            if interval_unit.lower() in ["year", "years"]:
                period_days = 365 * interval
            else:
                period_days = 30 * interval
            
            current_term_starts_at = zoho_subscription.get('current_term_starts_at')
            current_term_ends_at = zoho_subscription.get('current_term_ends_at')
            
            current_period_start = created_time
            if current_term_starts_at:
                try:
                    current_period_start = datetime.strptime(current_term_starts_at, "%Y-%m-%d")
                except:
                    pass
            
            current_period_end = current_period_start + timedelta(days=period_days)
            if current_term_ends_at:
                try:
                    current_period_end = datetime.strptime(current_term_ends_at, "%Y-%m-%d")
                except:
                    pass
            
            # Get subscription status from Zoho
            zoho_status = zoho_subscription.get('status', 'active')
            local_status = 'active' if zoho_status in ['live', 'active'] else zoho_status
            
            # Check if subscription already exists in local DB (by zoho_subscription_id)
            existing_subscription_result = await db.execute(
                select(Subscription)
                .where(Subscription.zoho_subscription_id == zoho_subscription_id)
                .order_by(Subscription.created_at.desc())
                .limit(1)
            )
            existing_subscription = existing_subscription_result.scalar_one_or_none()
            
            # Prepare metadata if provided
            metadata_json = None
            if subscription_request.metadata:
                import json
                metadata_json = json.dumps(subscription_request.metadata)
            
            if existing_subscription:
                # Update existing subscription
                await db.execute(
                    update(Subscription)
                    .where(Subscription.id == existing_subscription.id)
                    .values(
                        status=local_status,
                        subscription_status=local_status,
                        zoho_customer_id=zoho_customer_id,
                        amount=Decimal(str(zoho_subscription.get('amount', 0))),
                        currency_code=zoho_subscription.get('currency_code', 'USD'),
                        billing_cycle=billing_cycle,
                        auto_collect=zoho_subscription.get('auto_collect', True),
                        current_period_start=current_period_start,
                        current_period_end=current_period_end,
                        next_billing_date=next_billing_date,
                        updated_at=datetime.utcnow()
                    )
                )
                subscription_id = existing_subscription.id
            else:
                # Create new subscription in local database
                subscription_id = uuid.uuid4()
                subscription = Subscription(
                    id=subscription_id,
                    company_id=company.id,
                    plan_id=plan.id if plan else None,
                    status=local_status,
                    subscription_status=local_status,
                    amount=Decimal(str(zoho_subscription.get('amount', 0))),
                    currency_code=zoho_subscription.get('currency_code', 'USD'),
                    billing_cycle=billing_cycle,
                    auto_collect=zoho_subscription.get('auto_collect', True),
                    current_period_start=current_period_start,
                    current_period_end=current_period_end,
                    next_billing_date=next_billing_date,
                    zoho_subscription_id=zoho_subscription_id,
                    zoho_customer_id=zoho_customer_id,
                    usage_limits=subscription_request.metadata,  # Store metadata in usage_limits JSONB field
                    created_at=created_time,
                    updated_at=datetime.utcnow()
                )
                db.add(subscription)
            
            # Update company subscription plan
            if plan_code:
                await db.execute(
                    update(Company)
                    .where(Company.id == company.id)
                    .values(
                        subscription_plan=plan_code,
                        updated_at=datetime.utcnow()
                    )
                )
            
            await db.commit()
            logger.info(f"✅ Subscription {zoho_subscription_id} created in Zoho and saved to local database")
            
            return SuccessResponse(
                success=True,
                data=zoho_response,
                message="Subscription created successfully",
                code=status.HTTP_200_OK
            )
                
        except Exception as zoho_error:
            logger.error(f"Zoho API error: {zoho_error}")
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to create subscription: {str(zoho_error)}"
            )
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Exception at create subscription: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {str(e)}"
        )


@router.get("/zoho/subscriptions/fetchByHostedId/{hostedPageId}", response_model=SuccessResponse[dict])
async def fetch_by_hosted_id(
    hostedPageId: str,
    request: Request,
    platform_name: Optional[str] = None
):
    """
    Retrieve hosted page data by hosted page ID.
    
    This endpoint fetches hosted page information from Zoho.
    
    Args:
        platform_name: Platform name (e.g., 'prism7', 'accsell', 'zaptag'). If one of these, uses that platform's Zoho configuration.
    """
    try:
        # Get current user for authentication
        user = await get_current_user_required(request)
        
        # Verify user is company admin
        if user.role != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only company admins can access hosted page data"
            )
        
        # Get appropriate Zoho service instance based on platform_name (for future Zoho API calls)
        zoho_service_instance = get_zoho_service(platform_name)
        
        # For now, return a placeholder response as per Node.js implementation
        # In a real implementation, this would fetch data from Zoho API using zoho_service_instance
        base_url = zoho_service_instance.base_url.replace('/billing/v1', '') if zoho_service_instance.base_url else 'https://zoho.com'
        hosted_page_data = {
            "hostedPageId": hostedPageId,
            "status": "active",
            "url": f"{base_url}/hosted-page/{hostedPageId}"
        }
        
        return SuccessResponse(
            success=True,
            data=hosted_page_data,
            message="Hosted page retrieved successfully",
            code=status.HTTP_200_OK
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve hosted page: {str(e)}"
        )


@router.post("/zoho/subscriptions/updateCompanyPlan", response_model=SuccessResponse[dict])
async def update_company_plan(
    request_data: Dict[str, Any],
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Update company plan after successful payment.
    
    This endpoint updates the company's subscription plan in the local database only.
    The Zoho subscription has already been created/updated through the hosted page flow,
    so this endpoint only needs to sync the local database with the new plan.
    
    Flow:
    1. Frontend calls hostedPage/create → Creates hosted page in Zoho
    2. User completes payment on Zoho hosted page
    3. Frontend calls fetchByHostedId → Gets payment status
    4. Frontend calls this endpoint → Updates local database only
    """
    try:
        
        # Get current user for authentication
        user = await get_current_user_required(request)
        
        # Verify user is company admin
        if user.role != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only company admins can update company plans"
            )
        
        # Extract request data
        company_id = request_data.get("companyId")
        new_plan_id = request_data.get("newPlanId")
        subscription_id = request_data.get("subscriptionId")
        hosted_page_id = request_data.get("hostedPageId")
        customer_id = request_data.get("zohoCustomerId")  # Changed from customerId to zohoCustomerId
        platform_name = request_data.get("platform_name")
        
        if not company_id or not new_plan_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Company ID and new plan ID are required"
            )
        
        # Check if organization exists
        company_result = await db.execute(
            select(Company).where(Company.id == company_id)
        )
        company = company_result.scalar_one_or_none()
        
        if not company:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Organization not found"
            )
        
        # Check if plan exists
        plan_result = await db.execute(
            select(SubscriptionPlan).where(SubscriptionPlan.id == new_plan_id)
        )
        plan = plan_result.scalar_one_or_none()
        
        if not plan:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Plan not found"
            )
        
        # Mark all previous active subscriptions for this company as inactive
        # This allows us to track subscription history while keeping only one active subscription
        await db.execute(
            update(Subscription)
            .where(
                Subscription.company_id == company_id,
                Subscription.status.in_(["active", "trial"])
            )
            .values(
                status="inactive",
                subscription_status="inactive",
                updated_at=datetime.utcnow()
            )
        )
        
        # Always create a new subscription to track upgrade history
        subscription_id_new = uuid.uuid4()
        # Determine billing cycle and period end
        billing_cycle = plan.zoho_billing_cycle or (plan.interval_unit if plan.interval_unit else "monthly")
        # Ensure billing_cycle is a string and handle edge cases
        if not billing_cycle or not isinstance(billing_cycle, str):
            billing_cycle = "monthly"
        if billing_cycle.lower() in ["yearly", "year", "annual"]:
            period_days = 365
        else:
            period_days = 30  # Default to monthly
        
        current_period_start = datetime.utcnow()
        current_period_end = current_period_start + timedelta(days=period_days)
        
        new_subscription = Subscription(
            id=subscription_id_new,
            company_id=company_id,
            plan_id=new_plan_id,
            status="active",
            subscription_status="active",
            amount=plan.monthly_price,
            currency_code="USD",
            billing_cycle=billing_cycle,
            auto_collect=True,
            current_period_start=current_period_start,
            current_period_end=current_period_end,
            next_billing_date=current_period_end,
            zoho_subscription_id=subscription_id,
            zoho_customer_id=customer_id,
            zoho_payment_id=hosted_page_id,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        db.add(new_subscription)
        
        # Update company subscription plan
        await db.execute(
            update(Company)
            .where(Company.id == company_id)
            .values(
                subscription_plan=plan.plan_code,
                updated_at=datetime.utcnow()
            )
        )
        
        # Note: No need to update Zoho subscription here because:
        # 1. The hosted page creation already created/updated the subscription in Zoho
        # 2. The payment was processed through Zoho's hosted page
        # 3. This endpoint only needs to update the local database to reflect the new plan
        print(f"✅ Local database updated successfully for company {company_id} with plan {new_plan_id}")
        
        await db.commit()
        
        return SuccessResponse(
            success=True,
            data={
                "companyId": company_id,
                "newPlanId": new_plan_id,
                "subscriptionId": subscription_id,
                "hostedPageId": hosted_page_id,
                "zohoCustomerId": customer_id  # Changed from customerId to zohoCustomerId
            },
            message="Company plan updated successfully",
            code=status.HTTP_200_OK
        )
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update company plan: {str(e)}"
        )


@router.put("/zoho/subscriptions/hostedPage/update", response_model=SuccessResponse[dict])
async def update_subscription_hosted_page(
    subscription_request: SubscriptionUpdateRequest,
    request: Request
):
    """
    Create a hosted page for updating a subscription.
    
    This endpoint creates a Zoho hosted payment page that allows customers
    to update their subscription (change plan, add addons, etc.).
    
    Reference: https://www.zoho.com/billing/api/v1/hosted-pages/#update-a-subscription
    """
    try:
        # Validate request
        if not subscription_request:
            return SuccessResponse(
                success=False,
                data=None,
                message="Subscription request is required",
                code=status.HTTP_400_BAD_REQUEST
            )
        
        # Get current user for authentication
        user = await get_current_user_required(request)
        
        # Verify user is company admin
        if user.role != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only company admins can update subscriptions"
            )
        
        # Get platform_name from request
        platform_name = subscription_request.platform_name
        
        # Get appropriate Zoho service instance based on platform_name
        zoho_service_instance = get_zoho_service(platform_name)
        
        # Convert Pydantic model to dict for service
        subscription_data = subscription_request.model_dump(exclude_none=True)
        
        # Call Zoho service to create update subscription hosted page
        try:
            zoho_response = await zoho_service_instance.update_subscription_hosted_page(subscription_data)
            
            if zoho_response and zoho_response.get('hostedPageId'):
                return SuccessResponse(
                    success=True,
                    data=zoho_response,
                    message="Hosted page for subscription update created successfully",
                    code=status.HTTP_200_OK
                )
            else:
                return SuccessResponse(
                    success=False,
                    data=None,
                    message="Failed to create hosted page for subscription update",
                    code=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
                
        except Exception as zoho_error:
            logger.error(f"Zoho API error: {zoho_error}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to create hosted page: {str(zoho_error)}"
            )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Exception at update subscription hosted page: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {str(e)}"
        )
@router.post("/zoho/subscriptions/cancel", response_model=SuccessResponse[dict])
async def cancel_subscription_new(
    subscription_request: SubscriptionCancelRequest,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Cancel a subscription in Zoho and update local database.

    This endpoint cancels a subscription in Zoho and updates the local database
    subscription status accordingly.

    Note: If you may need to reactivate later, use cancelAtEnd: true (non_renewing).
    Immediate cancel (cancelAtEnd: false) terminates the subscription in Zoho; some
    Zoho setups do not allow reactivating immediately-cancelled subscriptions.

    Reference: https://www.zoho.com/billing/api/v1/subscription/#cancel-a-subscription
    """
    try:
        # Get current user for authentication (matches Java: getResourceMainFromAuthHeader)
        user = await get_current_user_required(request)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unauthorized"
            )
        
        subscription_id = subscription_request.subscriptionId
        cancel_at_end = subscription_request.cancelAtEnd
        platform_name = subscription_request.platform_name
        
        # Get appropriate Zoho service instance
        zoho_service_instance = get_zoho_service(platform_name)
        
        # Call Zoho service to cancel subscription
        try:
            zoho_response = await zoho_service_instance.cancel_subscription(
                subscription_id=subscription_id,
                cancel_at_end=cancel_at_end
            )
            
            if not zoho_response:
                return SuccessResponse(
                    success=False,
                    data=None,
                    message="Failed to cancel subscription",
                    code=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
            
            # Update local database subscription
            # Find subscription by zoho_subscription_id - get the latest one only
            subscription_result = await db.execute(
                select(Subscription)
                .where(Subscription.zoho_subscription_id == subscription_id)
                .order_by(Subscription.created_at.desc())
                .limit(1)
            )
            subscription = subscription_result.scalar_one_or_none()
            
            if subscription:
                # Extract subscription data from Zoho response
                subscription_data = zoho_response.get('subscription', {})
                
                # Prepare update values
                update_values = {
                    "status": "inactive",
                    "subscription_status": "inactive",
                    "updated_at": datetime.utcnow()
                }
                
                # Update current_term_ends_at if available in Zoho response
                current_term_ends_at = subscription_data.get('current_term_ends_at')
                if current_term_ends_at:
                    try:
                        # Parse the date string (format: "2016-06-05")
                        # Zoho returns date in YYYY-MM-DD format
                        end_date = datetime.strptime(current_term_ends_at, "%Y-%m-%d")
                        update_values["current_period_end"] = end_date
                        logger.info(f"🔄 Updating current_period_end to: {end_date}")
                    except Exception as date_error:
                        logger.warning(f"Could not parse current_term_ends_at: {date_error}")
                
                # Update zoho_cancel_at_period_end based on cancel_at_end flag
                # If cancel_at_end is True, subscription will cancel at period end
                # If cancel_at_end is False, subscription is cancelled immediately
                update_values["zoho_cancel_at_period_end"] = cancel_at_end if cancel_at_end is not None else False
                
                # Update subscription in database
                await db.execute(
                    update(Subscription)
                    .where(Subscription.id == subscription.id)
                    .values(**update_values)
                )
                
                await db.commit()
                logger.info(f"✅ Local database updated for subscription {subscription_id} - status set to inactive")
            else:
                logger.warning(f"⚠️ Subscription with zoho_subscription_id {subscription_id} not found in local database")
            
            return SuccessResponse(
                success=True,
                data=zoho_response,
                message="Subscription cancelled successfully",
                code=status.HTTP_200_OK
            )
                
        except Exception as zoho_error:
            logger.error(f"Zoho API error: {zoho_error}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to cancel subscription: {str(zoho_error)}"
            )
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Exception at cancel subscription: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {str(e)}"
        )


@router.post("/zoho/subscriptions/reactivate", response_model=SuccessResponse[dict])
async def reactivate_zoho_subscription(
    reactivate_request: SubscriptionReactivateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Reactivate a cancelled subscription in Zoho and update local database.
    Calls Zoho POST /subscriptions/{subscription_id}/reactivate and sets local subscription status to active.
    Reference: https://www.zoho.com/billing/api/v1/subscription/#reactivate-subscription
    This endpoint is additive only: it does not modify cancel/create/validatePayment or any other existing flow.
    """
    try:
        # Require authenticated user
        user = await get_current_user_required(request)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unauthorized"
            )
        subscription_id = reactivate_request.subscriptionId
        platform_name = reactivate_request.platform_name
        billing_cycles = reactivate_request.billingCycles if reactivate_request.billingCycles is not None else 12
        zoho_service_instance = get_zoho_service(platform_name)
        # Call Zoho API to reactivate subscription (Zoho requires billing_cycles in body)
        try:
            zoho_response = await zoho_service_instance.reactivate_subscription(
                subscription_id=subscription_id,
                billing_cycles=billing_cycles
            )
            if not zoho_response:
                return SuccessResponse(
                    success=False,
                    data=None,
                    message="Failed to reactivate subscription in Zoho",
                    code=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
            # Update local subscription: set status to active and clear cancel-at-period-end flag
            subscription_result = await db.execute(
                select(Subscription)
                .where(Subscription.zoho_subscription_id == subscription_id)
                .order_by(Subscription.created_at.desc())
                .limit(1)
            )
            subscription = subscription_result.scalar_one_or_none()
            if subscription:
                # Safely get subscription object from Zoho response (may be nested or top-level)
                subscription_data = zoho_response.get("subscription") if isinstance(zoho_response, dict) else {}
                if not isinstance(subscription_data, dict):
                    subscription_data = {}
                zoho_status = subscription_data.get("status", "live")
                local_status = "active" if zoho_status in ("live", "active") else zoho_status
                update_values = {
                    "status": local_status,
                    "subscription_status": local_status,
                    "zoho_cancel_at_period_end": False,
                    "updated_at": datetime.utcnow(),
                }
                # Optionally sync next_billing_at / current_term_ends_at from Zoho if present
                next_billing_at = subscription_data.get("next_billing_at")
                if next_billing_at:
                    try:
                        update_values["next_billing_date"] = datetime.strptime(next_billing_at, "%Y-%m-%d")
                    except Exception:
                        pass
                current_term_ends_at = subscription_data.get("current_term_ends_at")
                if current_term_ends_at:
                    try:
                        update_values["current_period_end"] = datetime.strptime(current_term_ends_at, "%Y-%m-%d")
                    except Exception:
                        pass
                await db.execute(
                    update(Subscription).where(Subscription.id == subscription.id).values(**update_values)
                )
                await db.commit()
                logger.info(f"✅ Subscription {subscription_id} reactivated in Zoho and local DB set to {local_status}")
            else:
                logger.warning(f"⚠️ Subscription with zoho_subscription_id {subscription_id} not found in local database")
            return SuccessResponse(
                success=True,
                data=zoho_response,
                message="Subscription reactivated successfully",
                code=status.HTTP_200_OK
            )
        except Exception as zoho_error:
            logger.error(f"Zoho API error on reactivate: {zoho_error}")
            err_str = str(zoho_error)
            # Zoho validation errors (invalid subscription ID 107202, invalid billing cycles 101017, etc.) → 400 Bad Request
            if "400" in err_str and ("107202" in err_str or "101017" in err_str or "valid" in err_str.lower()):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=err_str.replace("Zoho API error: 400 - ", "").strip() or "Invalid request to Zoho (check subscription ID and billing cycles)."
                )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to reactivate subscription: {err_str}"
            )
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Exception at reactivate subscription: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {str(e)}"
        )


@router.post("/zoho/subscriptions/validatePayment", response_model=SuccessResponse[dict])
async def validate_payment(
    subscription_request: ValidatePaymentRequest,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Validate payment and activate company.
    
    This endpoint validates payment by checking the hosted page or subscription status
    in Zoho, and if payment is successful, activates the company.
    
    Reference: https://www.zoho.com/billing/api/v1/hosted-pages/#retrieve-a-hosted-page
    """
    try:
        # Get user - use userId from request if provided, otherwise use current user
        user = None
        if subscription_request.userId:
            user_result = await db.execute(
                select(User).where(User.id == subscription_request.userId)
            )
            user = user_result.scalar_one_or_none()
            if not user:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="User not found"
                )
        else:
            user = await get_current_user_required(request)
        
        company_id = subscription_request.companyId
        hosted_page_id = subscription_request.hostedPageId
        subscription_id = subscription_request.subscriptionId
        platform_name = subscription_request.platform_name
        
        # Get appropriate Zoho service instance
        zoho_service_instance = get_zoho_service(platform_name)
        
        subscription_data = None
        zoho_response = None
        invoice_data = None
        
        # If hostedPageId is provided, retrieve hosted page
        if hosted_page_id:
            try:
                zoho_response = await zoho_service_instance.get_hosted_page(hosted_page_id)
                
                # Extract subscription data from response
                # According to Zoho API, subscription data is in response.data.subscription
                data = zoho_response.get('data', {})
                subscription_data = data.get('subscription', {})
                invoice_data = data.get('invoice', {})
                
                if not subscription_data:
                    logger.warning(f"No subscription data found in hosted page response")
                    return SuccessResponse(
                        success=False,
                        data=None,
                        message="Payment validation failed: No subscription data found",
                        code=status.HTTP_400_BAD_REQUEST
                    )
                
                # Get subscription_id from subscription data if not already provided
                if not subscription_id:
                    subscription_id = subscription_data.get('subscription_id')
                
            except Exception as zoho_error:
                logger.error(f"Zoho API error retrieving hosted page: {zoho_error}")
                return SuccessResponse(
                    success=False,
                    data=None,
                    message=f"Failed to retrieve hosted page: {str(zoho_error)}",
                    code=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
        
        # If subscriptionId is provided but no subscription_data yet, fetch subscription directly
        elif subscription_id:
            try:
                subscription_response = await zoho_service_instance.get_subscription(subscription_id)
                subscription_data = subscription_response.get('subscription', {})
                
                if not subscription_data:
                    logger.warning(f"No subscription data found for subscription {subscription_id}")
                    return SuccessResponse(
                        success=False,
                        data=None,
                        message="Payment validation failed: No subscription data found",
                        code=status.HTTP_400_BAD_REQUEST
                    )
            except Exception as zoho_error:
                logger.error(f"Zoho API error retrieving subscription: {zoho_error}")
                return SuccessResponse(
                    success=False,
                    data=None,
                    message=f"Failed to retrieve subscription: {str(zoho_error)}",
                    code=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
        else:
            return SuccessResponse(
                success=False,
                data=None,
                message="Either hostedPageId or subscriptionId must be provided",
                code=status.HTTP_400_BAD_REQUEST
            )
        
        # Validate payment
        subscription_status = subscription_data.get('status', '').lower()
        subscription_id_from_data = subscription_data.get('subscription_id')
        
        if not subscription_id_from_data:
            return SuccessResponse(
                success=False,
                data=None,
                message="Payment validation failed: Invalid subscription data",
                code=status.HTTP_400_BAD_REQUEST
            )
        
        # Check if subscription status is "live"
        if subscription_status != 'live':
            logger.warning(f"Subscription status is not 'live': {subscription_status}")
            return SuccessResponse(
                success=False,
                data=None,
                message=f"Payment validation failed: Subscription status is '{subscription_status}', expected 'live'",
                code=status.HTTP_400_BAD_REQUEST
            )
        
        # Validate payment - check if there's an invoice with payment made
        # Basic payment validation - check if subscription has amount > 0
        # In a real scenario, you might want to check invoice payment_made > 0 or balance == 0
        subscription_amount = subscription_data.get('amount', 0)
        is_payment_valid = True
        
        # If there's invoice data, check payment status
        if invoice_data:
            payment_made = invoice_data.get('payment_made', 0)
            balance = invoice_data.get('balance', 0)
            # Payment is valid if payment_made > 0 or balance == 0
            is_payment_valid = payment_made > 0 or balance == 0
        else:
            # If no invoice data, assume payment is valid if subscription status is "live"
            # This is a basic validation - in production, you might want stricter checks
            is_payment_valid = True
        
        if not is_payment_valid:
            logger.warning(f"Payment validation failed: Payment not confirmed")
            return SuccessResponse(
                success=False,
                data=None,
                message="Payment validation failed: Payment not confirmed",
                code=status.HTTP_400_BAD_REQUEST
            )
        
        # Payment is valid - update company subscription and activate company
        try:
            # Get customer data
            customer = subscription_data.get('customer', {})
            customer_id = customer.get('customer_id')
            customer_email = customer.get('email')
            
            # Get plan data
            plan = subscription_data.get('plan', {})
            plan_code = plan.get('plan_code')
            plan_name = plan.get('name')
            
            # Verify company exists
            company_result = await db.execute(
                select(Company).where(Company.id == company_id)
            )
            company = company_result.scalar_one_or_none()
            
            if not company:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Company not found"
                )
            
            # Parse dates
            created_time_str = subscription_data.get('created_time')
            next_billing_at_str = subscription_data.get('next_billing_at')
            
            created_time = None
            next_billing_date = None
            
            if created_time_str:
                try:
                    # Parse ISO format datetime: "2016-06-05T23:10:16-0700" or "2016-06-05T23:10:16-07:00"
                    # Match pattern like "2016-06-05T23:10:16" or "2016-06-05T23:10:16-0700"
                    match = re.match(r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})', created_time_str)
                    if match:
                        created_time = datetime.strptime(match.group(1), "%Y-%m-%dT%H:%M:%S")
                    else:
                        # Try simple date format
                        created_time = datetime.strptime(created_time_str.split('T')[0], "%Y-%m-%d")
                except Exception as date_error:
                    logger.warning(f"Could not parse created_time: {date_error}")
                    created_time = datetime.utcnow()
            
            if next_billing_at_str:
                try:
                    # Parse date format: "2016-06-30"
                    next_billing_date = datetime.strptime(next_billing_at_str, "%Y-%m-%d")
                except Exception as date_error:
                    logger.warning(f"Could not parse next_billing_at: {date_error}")
            
            # Find or create subscription in local database
            subscription_result = await db.execute(
                select(Subscription).where(
                    Subscription.zoho_subscription_id == subscription_id_from_data
                )
            )
            subscription = subscription_result.scalar_one_or_none()
            
            if subscription:
                # Update existing subscription
                await db.execute(
                    update(Subscription)
                    .where(Subscription.id == subscription.id)
                    .values(
                        status="active",
                        subscription_status="active",
                        zoho_customer_id=customer_id,
                        updated_at=datetime.utcnow()
                    )
                )
                if next_billing_date:
                    await db.execute(
                        update(Subscription)
                        .where(Subscription.id == subscription.id)
                        .values(
                            next_billing_date=next_billing_date,
                            updated_at=datetime.utcnow()
                        )
                    )
            else:
                # Create new subscription - we need plan_id from plan_code
                plan_result = await db.execute(
                    select(SubscriptionPlan).where(SubscriptionPlan.plan_code == plan_code)
                )
                plan_obj = plan_result.scalar_one_or_none()
                
                if not plan_obj:
                    logger.warning(f"Plan with code {plan_code} not found in local database")
                else:
                    # Determine billing cycle and period end
                    billing_cycle = plan_obj.zoho_billing_cycle or (plan_obj.interval_unit if plan_obj.interval_unit else "monthly")
                    if not billing_cycle or not isinstance(billing_cycle, str):
                        billing_cycle = "monthly"
                    if billing_cycle.lower() in ["yearly", "year", "annual"]:
                        period_days = 365
                    else:
                        period_days = 30
                    
                    current_period_start = created_time or datetime.utcnow()
                    current_period_end = current_period_start + timedelta(days=period_days)
                    
                    new_subscription = Subscription(
                        id=uuid.uuid4(),
                        company_id=company_id,
                        plan_id=plan_obj.id,
                        status="active",
                        subscription_status="active",
                        amount=Decimal(str(subscription_amount)),
                        currency_code=subscription_data.get('currency_code', 'USD'),
                        billing_cycle=billing_cycle,
                        auto_collect=True,
                        current_period_start=current_period_start,
                        current_period_end=current_period_end,
                        next_billing_date=next_billing_date or current_period_end,
                        zoho_subscription_id=subscription_id_from_data,
                        zoho_customer_id=customer_id,
                        created_at=created_time or datetime.utcnow(),
                        updated_at=datetime.utcnow()
                    )
                    db.add(new_subscription)
            
            # Update company subscription plan and activate company
            if plan_code:
                await db.execute(
                    update(Company)
                    .where(Company.id == company_id)
                    .values(
                        subscription_plan=plan_code,
                        is_active=True,  # Activate company
                        updated_at=datetime.utcnow()
                    )
                )
            
            # Update other subscriptions for this company to inactive
            # Mark other active subscriptions for this company as inactive
            await db.execute(
                update(Subscription)
                .where(
                    Subscription.company_id == company_id,
                    Subscription.zoho_subscription_id != subscription_id_from_data,
                    Subscription.status.in_(["active", "trial"])
                )
                .values(
                    status="inactive",
                    subscription_status="inactive",
                    updated_at=datetime.utcnow()
                )
            )
            
            await db.commit()
            logger.info(f"✅ Payment validated and company {company_id} activated successfully")
            
            return SuccessResponse(
                success=True,
                data={
                    "subscriptionId": subscription_id_from_data,
                    "companyId": company_id,
                    "status": "active",
                    "planCode": plan_code,
                    "planName": plan_name
                },
                message="Payment validated and company activated successfully",
                code=status.HTTP_200_OK
            )
            
        except Exception as db_error:
            await db.rollback()
            logger.error(f"Database error during payment validation: {db_error}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to update database: {str(db_error)}"
            )
        
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"Exception at validate payment: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {str(e)}"
        )


@router.post("/zoho/webhook/subscription", response_model=SuccessResponse[dict])
async def zoho_subscription_webhook(
    webhook_data: Dict[str, Any],
    request: Request
):
    """
    Webhook endpoint for Zoho subscription updates.
    
    Called by Zoho when subscription status changes.
    Note: Webhooks come from Zoho, not from UI, so platform_name may not be in the request.
    If needed, platform_name can be determined from subscription data in the database.
    """
    try:
        # Extract platform_name from webhook_data if present (for future use)
        platform_name = webhook_data.get("platform_name")
        
        # Get appropriate Zoho service instance if platform_name is provided
        # (for future Zoho API calls if needed)
        if platform_name:
            zoho_service_instance = get_zoho_service(platform_name)
        
        # Verify webhook signature (implement proper verification)
        # For now, we'll just log the webhook data
        
        print(f"Zoho webhook received: {json.dumps(webhook_data, indent=2)}")
        if platform_name:
            print(f"Platform name from webhook: {platform_name}")
        
        # Process webhook data and update subscription status
        # This would typically involve:
        # 1. Verifying webhook signature
        # 2. Updating subscription status in database
        # 3. Sending notifications if needed
        
        return SuccessResponse(
            success=True,
            data={"webhook_processed": True},
            message="Webhook processed successfully",
            code=status.HTTP_200_OK
        )
        
    except Exception as e:
        print(f"Error processing Zoho webhook: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process webhook: {str(e)}"
        )


def _parse_channel_limit_from_features(features: Any) -> int:
    """
    Parse channel limit from subscription_plan features JSON.
    Features format example: ["4 Channels", "10GB Storage"] or ["Unlimited Channels"]
    Returns the numeric limit, -1 for unlimited, or 0 if not found.
    """
    if features is None:
        return 0
    if isinstance(features, list):
        for item in features:
            if isinstance(item, str):
                # Check for "Unlimited Channels" first
                if re.search(r"unlimited\s+channels?", item, re.IGNORECASE):
                    return -1  # -1 indicates unlimited
                # Check for numeric channel limit
                m = re.search(r"(\d+)\s*Channels?", item, re.IGNORECASE)
                if m:
                    return int(m.group(1))
    if isinstance(features, dict):
        for k, v in features.items():
            if "channel" in str(k).lower():
                if isinstance(v, str) and re.search(r"unlimited", v, re.IGNORECASE):
                    return -1  # -1 indicates unlimited
                elif isinstance(v, (int, float)):
                    return int(v)
    return 0


def _parse_message_limit_from_features(features: Any) -> int:
    """
    Parse message limit (per channel) from subscription_plan features JSON.
    Features format example: ["4 Channels", "50 messages", "10GB Storage"] or ["Unlimited Messages"]
    Returns the numeric limit per channel, -1 for unlimited, or 0 if not found.
    """
    if features is None:
        return 0
    if isinstance(features, list):
        for item in features:
            if isinstance(item, str):
                # Check for "Unlimited Messages" first
                if re.search(r"unlimited\s+messages?", item, re.IGNORECASE):
                    return -1  # -1 indicates unlimited
                # Check for numeric message limit (handles "2000 Messages per Channel" pattern)
                m = re.search(r"(\d+)\s*Messages?", item, re.IGNORECASE)
                if m:
                    return int(m.group(1))
    if isinstance(features, dict):
        for k, v in features.items():
            if "message" in str(k).lower():
                if isinstance(v, str) and re.search(r"unlimited", v, re.IGNORECASE):
                    return -1  # -1 indicates unlimited
                elif isinstance(v, (int, float)):
                    return int(v)
    return 0


def _parse_storage_limit_from_features(features: Any) -> int:
    """
    Parse storage limit (in bytes) from subscription_plan features JSON.
    Features format example: ["4 Channels", "10GB Storage"] or ["Unlimited Storage"]
    Supports: GB, MB, KB, B (case-insensitive)
    Returns the limit in bytes, -1 for unlimited, or 0 if not found.
    """
    if features is None:
        return 0
    
    if isinstance(features, list):
        for item in features:
            if isinstance(item, str):
                # Check for "Unlimited Storage" first
                if re.search(r"unlimited\s+storage", item, re.IGNORECASE):
                    return -1  # -1 indicates unlimited
                # Match patterns like "10GB Storage", "10 GB", "10GB", "200 MB Data Storage per Channel", etc.
                m = re.search(r"(\d+(?:\.\d+)?)\s*(GB|MB|KB|B).*?Storage", item, re.IGNORECASE)
                if m:
                    size_value = float(m.group(1))
                    unit = m.group(2).upper()
                    
                    # Convert to bytes
                    if unit == "GB":
                        return int(size_value * 1024 * 1024 * 1024)
                    elif unit == "MB":
                        return int(size_value * 1024 * 1024)
                    elif unit == "KB":
                        return int(size_value * 1024)
                    elif unit == "B":
                        return int(size_value)
    
    if isinstance(features, dict):
        for k, v in features.items():
            if "storage" in str(k).lower():
                if isinstance(v, str) and re.search(r"unlimited", v, re.IGNORECASE):
                    return -1  # -1 indicates unlimited
                elif isinstance(v, (int, float)):
                    # Assume bytes if numeric
                    return int(v)
                elif isinstance(v, str):
                    # Parse string like "10GB"
                    m = re.search(r"(\d+(?:\.\d+)?)\s*(GB|MB|KB|B)", v, re.IGNORECASE)
                    if m:
                        size_value = float(m.group(1))
                        unit = m.group(2).upper()
                        if unit == "GB":
                            return int(size_value * 1024 * 1024 * 1024)
                        elif unit == "MB":
                            return int(size_value * 1024 * 1024)
                        elif unit == "KB":
                            return int(size_value * 1024)
                        elif unit == "B":
                            return int(size_value)
    return 0


async def _get_channel_storage_total(db: AsyncSession, channel_id: Any) -> int:
    """
    Return total storage in bytes for a channel: Attachment + EmailAttachment + Datasource file_size.
    Used for both marketplace (vs MARKETPLACE_STORAGE_LIMIT_MB) and SaaS (vs plan storage limit).
    """
    attachment_size_result = await db.execute(
        select(func.coalesce(func.sum(Attachment.file_size), 0)).where(
            Attachment.channel_id == channel_id
        )
    )
    attachment_size = attachment_size_result.scalar() or 0
    email_attachment_size_result = await db.execute(
        select(func.coalesce(func.sum(EmailAttachment.file_size), 0)).where(
            EmailAttachment.channel_id == channel_id
        )
    )
    email_attachment_size = email_attachment_size_result.scalar() or 0
    datasource_size_result = await db.execute(
        select(func.coalesce(func.sum(Datasource.file_size), 0)).where(
            Datasource.channel_id == channel_id
        )
    )
    datasource_size = datasource_size_result.scalar() or 0
    return int(attachment_size) + int(email_attachment_size) + int(datasource_size)


@router.post("/zoho/subscriptions/validation/{user_id}", response_model=SuccessResponse[dict])
async def subscription_validation(
        user_id: str,
        request: Request,
        db: AsyncSession = Depends(get_db),
        validation_request: Optional[SubscriptionValidationRequest] = Body(None),
):
    """
    Validate channel/message (and optionally attachment) limits in a single request.

    **channelId is optional.** For "can we create a channel?" only user_id is needed
    (no channel exists yet). Send channelId only when validating message (or attachment)
    count in an existing channel.

    When IS_MARKETPLACE is true: no plan or subscription is checked. Limits come from
    env (CHANNEL_COUNT, MESSAGE_COUNT, MARKETPLACE_STORAGE_LIMIT_MB). Channel, message,
    and attachment/datasource storage (200MB per channel by default) are validated.

    When IS_MARKETPLACE is false: requires active subscription and plan; channel,
    message, and attachment limits are read from plan features.

    Returns:
    - **canCreateChannel**: Can the company create more channels? (always checked; no channelId needed)
    - **canCreateMessage**: Can the company create more messages in this channel? (requires channelId in body)
    - **canCreateAttachment**: Can the company add more attachments/datasource in this channel? (requires channelId; in marketplace uses 200MB per channel limit)

    Request body: optional. If omitted, only canCreateChannel is validated.
    - channelId (optional): Omit for channel-only check. Provide a valid channel UUID when checking message/attachment limits.
    """
    try:
        # Validate UUIDs to avoid DB DataError when client sends placeholders (e.g. "string")
        if not _is_valid_uuid(user_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="user_id must be a valid UUID",
            )
        # Treat empty or placeholder values as "not provided" so channel-only check works without a real channelId
        channel_id_raw = validation_request.channelId if validation_request else None
        if channel_id_raw is None or (isinstance(channel_id_raw, str) and channel_id_raw.strip() == ""):
            channel_id = None
        elif isinstance(channel_id_raw, str) and channel_id_raw.strip().lower() in ("string", "uuid", "channel_id"):
            channel_id = None
        else:
            channel_id = channel_id_raw.strip() if isinstance(channel_id_raw, str) else channel_id_raw
            if not _is_valid_uuid(channel_id):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="channelId must be a valid UUID when provided",
                )

        user_result = await db.execute(select(User).where(User.id == user_id))
        user = user_result.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        company_id = user.company_id

        # Initialize response data
        response_data = {}

        if not company_id:
            response_data = {
                "canCreateChannel": False,
                "canCreateMessage": False if channel_id else None,
                "canCreateAttachment": False if channel_id else None,
            }
            return SuccessResponse(success=True, data=response_data, message="User has no company", code=status.HTTP_200_OK)

        # Marketplace: do not check subscription or plan; use only env limits for channel and message
        if settings.IS_MARKETPLACE:
            channel_limit = settings.CHANNEL_COUNT
            if channel_limit <= 0:
                response_data["canCreateChannel"] = False
            else:
                count_result = await db.execute(select(func.count()).select_from(Channel).where(Channel.company_id == company_id))
                current_count = count_result.scalar() or 0
                response_data["canCreateChannel"] = current_count < channel_limit

            if channel_id:
                ch_result = await db.execute(select(Channel).where(Channel.id == channel_id))
                ch = ch_result.scalar_one_or_none()
                if not ch or str(ch.company_id) != str(company_id):
                    response_data["canCreateMessage"] = False
                    response_data["canCreateAttachment"] = False
                else:
                    msg_limit = settings.MESSAGE_COUNT
                    if msg_limit <= 0:
                        response_data["canCreateMessage"] = False
                    else:
                        msg_count_result = await db.execute(
                            select(func.count()).select_from(Message).where(
                                Message.channel_id == channel_id,
                                Message.message_type.in_(["user", "email"]),
                            )
                        )
                        current_msg_count = msg_count_result.scalar() or 0
                        response_data["canCreateMessage"] = current_msg_count < msg_limit
                    # Marketplace: 200MB per channel (attachments + datasources)
                    limit_bytes = settings.MARKETPLACE_STORAGE_LIMIT_MB * 1024 * 1024
                    total_size = await _get_channel_storage_total(db, channel_id)
                    response_data["canCreateAttachment"] = total_size < limit_bytes
            else:
                response_data["canCreateMessage"] = None
                response_data["canCreateAttachment"] = None
            return SuccessResponse(success=True, data=response_data, message="OK", code=status.HTTP_200_OK)

        # Non-marketplace: require active subscription and plan; use plan features for all validations
        sub_result = await db.execute(
            select(Subscription)
            .where(Subscription.company_id == company_id, Subscription.status == "active")
            .order_by(Subscription.created_at.desc())
            .limit(1)
        )
        subscription = sub_result.scalar_one_or_none()
        if not subscription:
            response_data = {
                "canCreateChannel": False,
                "canCreateMessage": False if channel_id else None,
                "canCreateAttachment": False if channel_id else None,
            }
            return SuccessResponse(success=True, data=response_data, message="No active subscription for company", code=status.HTTP_200_OK)

        plan_result = await db.execute(select(SubscriptionPlan).where(SubscriptionPlan.id == subscription.plan_id))
        plan = plan_result.scalar_one_or_none()
        if not plan:
            response_data = {
                "canCreateChannel": False,
                "canCreateMessage": False if channel_id else None,
                "canCreateAttachment": False if channel_id else None,
            }
            return SuccessResponse(success=True, data=response_data, message="Plan not found", code=status.HTTP_200_OK)

        # --- 1. Channel validation (always) ---
        channel_limit = _parse_channel_limit_from_features(plan.features)
        if channel_limit == -1:
            response_data["canCreateChannel"] = True
        elif channel_limit <= 0:
            response_data["canCreateChannel"] = False
        else:
            count_result = await db.execute(select(func.count()).select_from(Channel).where(Channel.company_id == company_id))
            current_count = count_result.scalar() or 0
            response_data["canCreateChannel"] = current_count < channel_limit

        # --- 2. Message validation (if channel_id provided) ---
        if channel_id:
            ch_result = await db.execute(select(Channel).where(Channel.id == channel_id))
            ch = ch_result.scalar_one_or_none()
            if not ch or str(ch.company_id) != str(company_id):
                response_data["canCreateMessage"] = False
                response_data["canCreateAttachment"] = False
            else:
                msg_limit = _parse_message_limit_from_features(plan.features)
                if msg_limit == -1:
                    response_data["canCreateMessage"] = True
                elif msg_limit <= 0:
                    response_data["canCreateMessage"] = False
                else:
                    msg_count_result = await db.execute(
                        select(func.count()).select_from(Message).where(
                            Message.channel_id == channel_id,
                            Message.message_type.in_(["user", "email"]),
                        )
                    )
                    current_msg_count = msg_count_result.scalar() or 0
                    response_data["canCreateMessage"] = current_msg_count < msg_limit

                storage_limit_bytes = _parse_storage_limit_from_features(plan.features)
                if storage_limit_bytes == -1:
                    response_data["canCreateAttachment"] = True
                elif storage_limit_bytes <= 0:
                    response_data["canCreateAttachment"] = False
                else:
                    # Total storage: attachments + email attachments + datasources
                    total_size = await _get_channel_storage_total(db, channel_id)
                    response_data["canCreateAttachment"] = total_size < storage_limit_bytes
        else:
            response_data["canCreateMessage"] = None
            response_data["canCreateAttachment"] = None

        return SuccessResponse(success=True, data=response_data, message="OK", code=status.HTTP_200_OK)

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Exception at subscription validation: %s", e)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Internal server error: {str(e)}")


@router.post("/zoho/subscriptions/fetchCompanySubscriptionDetails", response_model=SuccessResponse[CompanySubscriptionDetailsResponse])
async def fetch_company_subscription_details(
    request_data: CompanySubscriptionDetailsRequest,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
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


@router.post("/zoho/invoices/companyInvoiceDetails", response_model=SuccessResponse[CompanyInvoiceDetailsResponse])
async def fetch_company_invoice_details(
    request_data: CompanySubscriptionDetailsRequest,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Fetch invoice details for a company (same structure as fetchCompanySubscriptionDetails invoice section).

    Returns invoice list and total cost. Any authenticated user in the company can access.
    """
    try:
        user = await get_current_user_required(request)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unauthorized"
            )
        company_id = request_data.companyId
        # Validate companyId is a valid UUID to avoid DB errors
        try:
            uuid.UUID(company_id)
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid companyId format"
            )
        if str(user.company_id) != str(company_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User does not belong to the requested company"
            )
        invoice_details, total_cost = await _fetch_invoice_details_for_company(db, company_id)
        response_data = CompanyInvoiceDetailsResponse(
            invoiceDetails=invoice_details,
            totalCost=str(total_cost) if total_cost > 0 else None
        )
        return SuccessResponse(
            success=True,
            data=response_data,
            message="OK",
            code=status.HTTP_200_OK
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Exception at fetch company invoice details: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {str(e)}"
        )


@router.get("/zoho/invoices/{invoice_id}/download")
async def download_invoice(
    invoice_id: str,
    platform_name: Optional[str] = Query(None, description="Platform name (e.g., 'prism7')"),
    request: Request = None,
    db: AsyncSession = Depends(get_db)
):
    """
    Download invoice PDF from Zoho.
    
    This endpoint downloads the invoice PDF file from Zoho and returns it as a downloadable file.
    Only company admins can download invoices for their company.
    
    Args:
        invoice_id: The Zoho invoice ID
        platform_name: Platform name (e.g., 'prism7'). If 'prism7', uses PRISM Zoho configuration.
        
    Returns:
        PDF file as binary response with appropriate headers
    """
    try:
        # Log request details for debugging
        auth_header = request.headers.get("Authorization") if request else None
        user_id_from_state = getattr(request.state, "user_id", None) if request else None
        
        logger.info(f"🔍 Invoice download request - invoice_id: {invoice_id}, platform_name: {platform_name}")
        logger.info(f"🔍 Auth header present: {bool(auth_header)}")
        logger.info(f"🔍 User ID from request.state: {user_id_from_state}")
        
        # Get current user for authentication
        if not request:
            logger.error("❌ Request object is None")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Request object not found"
            )
        
        # Check if user_id is in request state (set by AuthMiddleware)
        if not user_id_from_state:
            logger.error("❌ No user_id in request.state - Authentication header missing or invalid")
            logger.error(f"❌ Authorization header: {auth_header[:50] + '...' if auth_header and len(auth_header) > 50 else auth_header}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required - Please provide a valid Bearer token in the Authorization header",
                headers={"WWW-Authenticate": "Bearer"}
            )
        
        try:
            user = await get_current_user_required(request, db)
            logger.info(f"✅ User authenticated: {user.id if user else 'None'}")
        except HTTPException as auth_error:
            logger.error(f"❌ Authentication failed: {auth_error.detail}, status: {auth_error.status_code}")
            raise
        except Exception as auth_ex:
            logger.error(f"❌ Authentication error: {str(auth_ex)}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Authentication failed: {str(auth_ex)}"
            )
        
        if not user:
            logger.error("❌ User is None after authentication")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unauthorized - User not found"
            )
        
        # Verify user is company admin
        if user.role != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only company admins can download invoices"
            )
        
        # Get company subscription to verify invoice belongs to user's company
        company_result = await db.execute(
            select(Company).where(Company.id == user.company_id)
        )
        company = company_result.scalar_one_or_none()
        
        if not company:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Company not found"
            )
        
        # Get subscription to verify customer_id matches
        subscription_result = await db.execute(
            select(Subscription)
            .where(Subscription.company_id == company.id)
            .order_by(Subscription.created_at.desc())
            .limit(1)
        )
        subscription = subscription_result.scalar_one_or_none()
        
        # Default to 'prism7' if platform_name is not provided (since PRISM credentials are configured)
        effective_platform_name = platform_name if platform_name else 'prism7'
        
        if subscription and subscription.zoho_customer_id:
            # Verify invoice belongs to this customer by fetching invoice details
            zoho_service_instance = get_zoho_service(effective_platform_name)
            try:
                # Get invoice details to verify it belongs to the customer
                invoices = await zoho_service_instance.get_customer_invoices(subscription.zoho_customer_id)
                invoice_found = any(inv.get('invoice_id') == invoice_id for inv in invoices)
                
                if not invoice_found:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Invoice does not belong to your company"
                    )
            except Exception as verify_error:
                logger.warning(f"Could not verify invoice ownership: {verify_error}")
                # Continue with download attempt - Zoho API will handle authorization
        
        # Get appropriate Zoho service instance
        zoho_service_instance = get_zoho_service(effective_platform_name)
        
        # Download invoice PDF from Zoho
        try:
            pdf_content = await zoho_service_instance.download_invoice_pdf(invoice_id)
            
            # Return PDF as downloadable file
            return Response(
                content=pdf_content,
                media_type="application/pdf",
                headers={
                    "Content-Disposition": f'attachment; filename="invoice_{invoice_id}.pdf"',
                    "Content-Type": "application/pdf"
                }
            )
            
        except Exception as zoho_error:
            logger.error(f"Zoho API error downloading invoice: {zoho_error}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to download invoice: {str(zoho_error)}"
            )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Exception at download invoice: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {str(e)}"
        )
