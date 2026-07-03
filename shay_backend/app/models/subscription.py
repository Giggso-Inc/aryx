"""
Subscription model for managing company subscriptions to plans
"""

from sqlalchemy import Column, String, DateTime, Boolean, Numeric, Index, ForeignKey, UniqueConstraint
from app.core.db_types import UUID, JSONB
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from app.core.database import Base


class Subscription(Base):
    """Company subscription to a specific plan."""

    __tablename__ = "subscriptions"

    # Primary key
    id = Column(UUID(as_uuid=True), primary_key=True, index=True)
    
    # Foreign keys
    company_id = Column(UUID(as_uuid=True), ForeignKey("gg_company.id"), nullable=False, index=True)
    plan_id = Column(UUID(as_uuid=True), ForeignKey("subscription_plans.id"), nullable=False, index=True)
    
    # Subscription details
    status = Column(String(50), nullable=False, default="active", index=True)
    subscription_status = Column(String(50), nullable=False, default="active")
    
    # Billing information
    amount = Column(Numeric(10, 2), nullable=False)
    currency_code = Column(String(3), nullable=False, default="USD")
    billing_cycle = Column(String(50), nullable=False)
    auto_collect = Column(Boolean, nullable=False, default=True)
    
    # Billing periods
    current_period_start = Column(DateTime, nullable=False)
    current_period_end = Column(DateTime, nullable=False)
    next_billing_date = Column(DateTime, nullable=True)
    
    # Trial information
    zoho_trial_end = Column(DateTime, nullable=True)
    zoho_cancel_at_period_end = Column(Boolean, nullable=False, default=False)
    
    # Usage and limits
    usage_limits = Column(JSONB, nullable=True)
    
    # Zoho integration fields
    zoho_subscription_id = Column(String(255), nullable=True, unique=True)
    zoho_customer_id = Column(String(255), nullable=True)
    zoho_hosted_page_id = Column(String(255), nullable=True)
    zoho_invoice_id = Column(String(255), nullable=True)
    zoho_payment_id = Column(String(255), nullable=True)
    
    # Audit fields
    created_at = Column(DateTime, default=func.current_timestamp(), nullable=False)
    updated_at = Column(DateTime, default=func.current_timestamp(), onupdate=func.current_timestamp(), nullable=False)
    deleted_at = Column(DateTime, nullable=True)

    # Relationships
    company = relationship("Company", back_populates="subscriptions")
    plan = relationship("SubscriptionPlan")

    # Indexes and constraints
    __table_args__ = (
        Index("idx_subscriptions_company", "company_id"),
        Index("idx_subscriptions_plan", "plan_id"),
        Index("idx_subscriptions_status", "status"),
        Index("idx_subscriptions_active", "status", "current_period_end"),
        # Removed unique constraint on (company_id, plan_id) to allow subscription history tracking

    )

    def __repr__(self) -> str:
        return f"<Subscription(id={self.id}, company_id={self.company_id}, plan_id={self.plan_id}, status='{self.status}')>"
