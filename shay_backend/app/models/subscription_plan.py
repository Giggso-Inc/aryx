"""
SubscriptionPlan model for managing different subscription plan types
"""

from sqlalchemy import Column, String, DateTime, Boolean, Integer, Numeric, Index, UniqueConstraint
from app.core.db_types import UUID, JSONB
from sqlalchemy.sql import func

from app.core.database import Base


class SubscriptionPlan(Base):
    """Subscription plan configuration and pricing."""

    __tablename__ = "subscription_plans"

    # Primary key
    id = Column(UUID(as_uuid=True), primary_key=True, index=True)

    # Plan details
    name = Column(String(255), nullable=False, index=True)
    plan_code = Column(String(50), nullable=False, unique=True, index=True)
    description = Column(String, nullable=True)
    
    # Pricing
    monthly_price = Column(Numeric(10, 2), nullable=False)
    plan_cycles = Column(Integer, nullable=False, default=1)
    
    # Billing configuration
    interval = Column(Integer, nullable=False, default=1)
    interval_unit = Column(String(20), nullable=False, default="month")
    interval_count = Column(Integer, nullable=False, default=1)
    
    # Features and metadata
    features = Column(JSONB, nullable=True)
    sort_order = Column(Integer, nullable=False, default=0)
    is_active = Column(Boolean, nullable=False, default=True)
    
    # Zoho integration fields
    zoho_plan_id = Column(String(255), nullable=True)
    zoho_product_id = Column(String(255), nullable=True)
    zoho_plan_code = Column(String(255), nullable=True)
    zoho_product_code = Column(String(255), nullable=True)
    zoho_billing_cycle = Column(String(50), nullable=True)
    
    # Platform name field for filtering plans by platform
    platform_name = Column(String(50), nullable=True, index=True)
    
    # Audit fields
    created_by = Column(UUID(as_uuid=True), nullable=True)
    updated_by = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=func.current_timestamp(), nullable=False)
    updated_at = Column(DateTime, default=func.current_timestamp(), onupdate=func.current_timestamp(), nullable=False)
    deleted_at = Column(DateTime, nullable=True)

    # Indexes and constraints
    __table_args__ = (
        Index("idx_subscription_plans_active", "is_active"),
        Index("idx_subscription_plans_sort_order", "sort_order"),
        Index("idx_subscription_plans_plan_code", "plan_code"),
        Index("idx_subscription_plans_platform_name", "platform_name"),
        UniqueConstraint("plan_code", name="uq_subscription_plan_code"),
    )

    def __repr__(self) -> str:
        return f"<SubscriptionPlan(id={self.id}, name='{self.name}', plan_code='{self.plan_code}')>"
