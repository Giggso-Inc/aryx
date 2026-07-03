"""
Common schemas for standardized API responses.

This module contains common response schemas that provide consistent
API response formats across all endpoints.
"""

from typing import Generic, TypeVar, Optional, Any
from pydantic import BaseModel, Field

DataT = TypeVar('DataT')


class StandardResponse(BaseModel, Generic[DataT]):
    """Standard API response wrapper."""
    success: bool = Field(..., description="Whether the request was successful")
    data: Optional[DataT] = Field(None, description="Response data")
    message: str = Field(..., description="Response message")
    code: int = Field(..., description="HTTP status code")


class SuccessResponse(StandardResponse[DataT]):
    """Success response wrapper."""
    success: bool = Field(True, description="Request was successful")
    code: int = Field(200, description="HTTP 200 status code")


class ErrorResponse(BaseModel):
    """Error response wrapper."""
    success: bool = Field(False, description="Request failed")
    data: Optional[Any] = Field(None, description="Error details")
    message: str = Field(..., description="Error message")
    code: int = Field(..., description="HTTP error status code")


class ZohoHostedPageRequest(BaseModel):
    """Zoho hosted page creation request schema"""
    plan: dict = Field(..., description="Plan information")
    redirectUrl: str = Field(..., description="Redirect URL after payment")
    customer: dict = Field(..., description="Customer information")
    autoCollect: bool = Field(True, description="Auto collect payment")
    platform_name: Optional[str] = Field(None, description="Platform name (e.g., 'prism7', 'accsell', 'zaptag'). If one of these, uses that platform's Zoho configuration")


class ZohoHostedPageResponse(BaseModel):
    """Zoho hosted page creation response schema"""
    hostedPageId: str = Field(..., description="Hosted page ID")
    url: str = Field(..., description="Hosted page URL")
    planId: str = Field(..., description="Plan ID")
    planName: str = Field(..., description="Plan name")
    amount: float = Field(..., description="Amount")
    companyId: str = Field(..., description="Company ID")
    companyName: str = Field(..., description="Company name")
    expiresAt: str = Field(..., description="Expiration time")


class UpdateCompanyPlanRequest(BaseModel):
    """Request schema for updating company plan"""
    companyId: str = Field(..., description="Company ID")
    newPlanId: str = Field(..., description="New subscription plan ID")
    subscriptionId: Optional[str] = Field(None, description="Zoho subscription ID (optional)")
    hostedPageId: Optional[str] = Field(None, description="Zoho hosted page ID (optional)")
    zohoCustomerId: Optional[str] = Field(None, description="Zoho customer ID (optional)")



class SubscriptionUpdateRequest(BaseModel):
    """Request schema for updating subscription via hosted page"""
    subscriptionId: str = Field(..., description="Zoho subscription ID")
    plan: Optional[dict] = Field(None, description="Plan information for update")
    addons: Optional[list] = Field(None, description="List of addons")
    referenceId: Optional[str] = Field(None, description="Reference ID")
    startsAt: Optional[str] = Field(None, description="Start date for subscription")
    customFields: Optional[list] = Field(None, description="Custom fields")
    couponCode: Optional[str] = Field(None, description="Coupon code")
    redirectUrl: Optional[str] = Field(None, description="Redirect URL after payment")
    salespersonName: Optional[str] = Field(None, description="Sales person name")
    canChargeSetupFeeImmediately: Optional[bool] = Field(None, description="Charge setup fee immediately")
    exchangeRate: Optional[float] = Field(None, description="Exchange rate")
    placeOfSupply: Optional[str] = Field(None, description="Place of supply")
    gstTreatment: Optional[str] = Field(None, description="GST treatment")
    gstNo: Optional[str] = Field(None, description="GST number")
    cfdiUsage: Optional[str] = Field(None, description="CFDI usage")
    paymentGateways: Optional[list] = Field(None, description="Payment gateways")
    billingAddressId: Optional[str] = Field(None, description="Billing address ID")
    shippingAddressId: Optional[str] = Field(None, description="Shipping address ID")
    branchId: Optional[str] = Field(None, description="Branch ID")
    templateId: Optional[int] = Field(None, description="Template ID")
    platform_name: Optional[str] = Field(None, description="Platform name (e.g., 'prism7', 'accsell', 'zaptag'). If one of these, uses that platform's Zoho configuration")


class SubscriptionCancelRequest(BaseModel):
    """Request schema for canceling a subscription"""
    subscriptionId: str = Field(..., description="Zoho subscription ID")
    cancelAtEnd: bool = Field(False, description="If true, cancel at end of term (non_renewing), if false, cancel immediately (cancelled)")
    platform_name: Optional[str] = Field(None, description="Platform name (e.g., 'prism7', 'accsell', 'zaptag'). If one of these, uses that platform's Zoho configuration")


class SubscriptionReactivateRequest(BaseModel):
    """Request schema for reactivating a cancelled subscription"""
    subscriptionId: str = Field(..., min_length=1, description="Zoho subscription ID to reactivate")
    # Zoho requires billing_cycles (number of cycles after which subscription expires); use -1 for never expire, or e.g. 12 for 12 cycles
    billingCycles: Optional[int] = Field(12, description="Number of billing cycles for reactivated subscription; default 12. Use -1 for never expire.")
    platform_name: Optional[str] = Field(None, description="Platform name (e.g., 'prism7', 'accsell', 'zaptag'). If one of these, uses that platform's Zoho configuration")


class ValidatePaymentRequest(BaseModel):
    """Request schema for validating payment"""
    hostedPageId: Optional[str] = Field(None, description="Zoho hosted page ID")
    subscriptionId: Optional[str] = Field(None, description="Zoho subscription ID (used if hostedPageId is not provided)")
    companyId: str = Field(..., description="Company ID")
    userId: Optional[str] = Field(None, description="User ID (optional)")
    platform_name: Optional[str] = Field(None, description="Platform name (e.g., 'prism7', 'accsell', 'zaptag'). If one of these, uses that platform's Zoho configuration")


class SubscriptionValidationRequest(BaseModel):
    """Request schema for subscription validation. channelId is optional: omit it when only checking if the company can create a channel (user_id is enough); send it when checking message (and attachment) limits in an existing channel."""
    channelId: Optional[str] = Field(None, description="Optional. Omit when checking canCreateChannel only. Send a valid channel UUID when checking canCreateMessage (and canCreateAttachment).")


class SubscriptionCreateRequest(BaseModel):
    """Request schema for creating a subscription in Zoho"""
    customer: Optional[dict] = Field(None, description="Customer object (required for new customer)")
    customerId: Optional[str] = Field(None, description="Customer ID (required for existing customer)")
    plan: dict = Field(..., description="Plan information with plan_code, quantity, price, etc.")
    autoCollect: Optional[bool] = Field(True, description="Auto collect payment")
    referenceId: Optional[str] = Field(None, description="Reference ID")
    startsAt: Optional[str] = Field(None, description="Start date for subscription")
    addons: Optional[list] = Field(None, description="List of addons")
    couponCode: Optional[str] = Field(None, description="Coupon code")
    metadata: Optional[dict] = Field(None, description="Metadata for subscription")
    platform_name: Optional[str] = Field(None, description="Platform name (e.g., 'prism7', 'accsell', 'zaptag'). If one of these, uses that platform's Zoho configuration")


class CompanySubscriptionDetailsRequest(BaseModel):
    """Request schema for fetching company subscription details"""
    companyId: str = Field(..., description="Company ID")


class CompanyInvoiceDetailsResponse(BaseModel):
    """Response schema for company invoice details only (simple API)"""
    invoiceDetails: Optional[list] = None
    totalCost: Optional[str] = None


class SaveTokenDetailsRequest(BaseModel):
    """Request schema for public saveTokenDetails - token/config stored in vault without JWT."""
    token_type: str = Field(..., description="Token type (e.g. openai, anthropic, azure)")
    tokenName: str = Field(..., description="Display name for the token (stored in vault)")
    api_key: str = Field(..., description="API key to store securely in vault")
    embedding_model: str = Field(..., description="Embedding model identifier")
    gpt_model: str = Field(..., description="GPT/LLM model identifier")
    companyId: str = Field(..., description="Company ID to associate with the vault entry")
    # Azure-specific (required when token_type is azure)
    deploymentName: Optional[str] = Field(None, description="Azure deployment name (required when token_type is azure)")
    deploymentVersion: Optional[str] = Field(None, description="Azure deployment version (required when token_type is azure)")
    endpoint: Optional[str] = Field(None, description="Azure endpoint URL (required when token_type is azure)")


class SaveTokenDetailsResponse(BaseModel):
    """Response schema for saveTokenDetails - returns vault identifiers."""
    vault_unique_id: str = Field(..., description="Vault unique ID used for external vault storage")
    giggso_vault_id: str = Field(..., description="Primary key of the gg_vault record (UUID)")


class FetchTokenDetailsRequest(BaseModel):
    """Request schema for fetching token details for a company (authenticated)."""
    companyId: str = Field(..., description="Company ID to fetch token details for")


class FetchTokenDetailsResponse(BaseModel):
    """Response schema for fetching token details from vault."""
    vault_unique_id: str = Field(..., description="Vault unique ID used for external vault storage")
    giggso_vault_id: str = Field(..., description="Primary key of the gg_vault record (UUID)")
    token_details: dict = Field(..., description="Token details fetched from vault")


class DeleteTokenDetailsRequest(BaseModel):
    """Request schema for deleting token details for a company (authenticated)."""
    companyId: str = Field(..., description="Company ID to delete token details for")


class DeleteTokenDetailsResponse(BaseModel):
    """Response schema for deleting token details from vault + gg_vault."""
    deleted: bool = Field(..., description="Whether the delete operation completed")
    vault_unique_id: Optional[str] = Field(None, description="Vault unique ID that was deleted")
    giggso_vault_id: Optional[str] = Field(None, description="gg_vault record ID that was deleted")


class CompanySubscriptionDetailsResponse(BaseModel):
    """Response schema for company subscription details"""
    currentPlan: Optional[str] = None
    currentPlanCode: Optional[str] = None
    planPeriod: Optional[str] = None
    subscriptionId: Optional[str] = None
    customerId: Optional[str] = None
    userInfo: Optional[dict] = None
    currentCost: Optional[str] = None
    nextInvoiceDate: Optional[str] = None
    companyGroupCount: Optional[int] = None
    sharedInboxCount: Optional[int] = None
    companyChannelCount: Optional[int] = None
    aiResponseCount: Optional[int] = None
    storageCount: Optional[int] = None
    invoiceDetails: Optional[list] = None
    totalCost: Optional[str] = None
    status: Optional[str] = None
    currentPlanStatus: Optional[str] = None
    addonDetails: Optional[dict] = None
    metadata: Optional[dict] = None
    expiresAt: Optional[str] = None
    usageStatistics: Optional[dict] = None


class LLMValidatorRequest(BaseModel):
    """Request schema for LLM validation API"""
    llmType: str = Field(..., description="LLM type: 'azureopenai', 'chatgpt', or 'gemini'")
    llmApiKey: str = Field(..., description="Base64 encoded API key")
    llmModelName: str = Field(..., description="Model name (deployment name for Azure, model name for OpenAI/Gemini)")
    llmApiVersion: Optional[str] = Field(None, description="API version (required for Azure OpenAI)")
    llmEndpoint: Optional[str] = Field(None, description="Endpoint URL (required for Azure OpenAI)")


class LLMValidatorResponse(BaseModel):
    """Response schema for LLM validation API"""
    status: str = Field(..., description="Validation status: 'success' or 'failed'")
    type: str = Field(..., description="Error type if failed (e.g., 'invalid_key', 'quota_issue', 'resource_issue')")
    cost: float = Field(0.0, description="Cost of the validation request")
    message: str = Field(..., description="Validation message")