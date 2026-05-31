"""
ISP Multi-tenant Models
========================
Organization, ISPProfile, ISPPackage, EmailVerification
"""
import uuid
from datetime import datetime, timezone
from enum import Enum as PyEnum
from sqlalchemy import (
    Column, String, Boolean, DateTime,
    ForeignKey, Enum, Text, Integer, Numeric
)
from sqlalchemy.orm import relationship
from billing_system.models.models import Base

def _uuid(): return str(uuid.uuid4())
def _now():  return datetime.now(timezone.utc)


class SubscriptionPlan(PyEnum):
    STARTER  = "starter"   # KES 1,500 — up to 50 customers
    GROWTH   = "growth"    # KES 3,500 — up to 200 customers
    PRO      = "pro"       # KES 8,000 — unlimited


class ISPStatus(PyEnum):
    PENDING   = "pending"    # registered, email not verified
    ACTIVE    = "active"     # verified and paying
    SUSPENDED = "suspended"  # payment overdue
    CANCELLED = "cancelled"  # cancelled subscription


class Organization(Base):
    """
    One row per ISP company.
    All their data is isolated by org_id.
    """
    __tablename__ = "organizations"

    id               = Column(String(36), primary_key=True, default=_uuid)
    company_name     = Column(String(255), nullable=False)
    slug             = Column(String(100), unique=True, nullable=False, index=True)
    owner_id         = Column(String(36), ForeignKey("users.id"), nullable=False)
    status           = Column(Enum(ISPStatus), nullable=False, default=ISPStatus.PENDING)
    subscription_plan= Column(Enum(SubscriptionPlan), nullable=False, default=SubscriptionPlan.STARTER)
    email            = Column(String(255), nullable=False)
    helpline         = Column(String(30), nullable=True)
    address          = Column(Text, nullable=True)
    website          = Column(String(255), nullable=True)
    logo_url         = Column(String(500), nullable=True)
    # Theme customization
    theme_primary    = Column(String(7), nullable=False, default="#00e5a0")
    theme_secondary  = Column(String(7), nullable=False, default="#5b6af0")
    theme_bg         = Column(String(7), nullable=False, default="#0f1117")
    theme_pattern    = Column(String(50), nullable=False, default="hexagon_teal")
    # Subscription
    trial_ends_at    = Column(DateTime(timezone=True), nullable=True)
    subscribed_at    = Column(DateTime(timezone=True), nullable=True)
    next_billing_at  = Column(DateTime(timezone=True), nullable=True)
    monthly_fee      = Column(Numeric(10, 2), nullable=False, default=1500)
    # Stats
    max_customers    = Column(Integer, nullable=False, default=50)
    max_packages     = Column(Integer, nullable=False, default=12)
    created_at       = Column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at       = Column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)

    owner    = relationship("User", foreign_keys=[owner_id])
    packages = relationship("ISPPackage", back_populates="org", cascade="all, delete-orphan")

    def __repr__(self): return f"<Organization {self.company_name}>"


class ISPPackage(Base):
    """
    WiFi packages defined by each ISP.
    Max 12 per organization.
    """
    __tablename__ = "isp_packages"

    id           = Column(String(36), primary_key=True, default=_uuid)
    org_id       = Column(String(36), ForeignKey("organizations.id"), nullable=False, index=True)
    name         = Column(String(100), nullable=False)
    price        = Column(Numeric(10, 2), nullable=False)
    duration_hours= Column(Integer, nullable=False)
    data_limit_mb = Column(Integer, nullable=True)   # NULL = unlimited
    speed_mbps   = Column(Integer, nullable=True)    # NULL = full speed
    is_streaming  = Column(Boolean, nullable=False, default=False)
    description  = Column(String(255), nullable=True)
    is_active    = Column(Boolean, nullable=False, default=True)
    sort_order   = Column(Integer, nullable=False, default=0)
    created_at   = Column(DateTime(timezone=True), nullable=False, default=_now)

    org = relationship("Organization", back_populates="packages")

    def __repr__(self): return f"<ISPPackage {self.name} KES {self.price}>"


class EmailVerification(Base):
    """
    Email verification tokens for ISP registration.
    """
    __tablename__ = "email_verifications"

    id         = Column(String(36), primary_key=True, default=_uuid)
    user_id    = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    token      = Column(String(100), unique=True, nullable=False, index=True)
    email      = Column(String(255), nullable=False)
    is_used    = Column(Boolean, nullable=False, default=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)

    def __repr__(self): return f"<EmailVerification {self.email}>"


class ISPInvoice(Base):
    """
    Invoices YOU send to ISPs for their monthly subscription.
    Different from the billing invoices ISPs send to their customers.
    """
    __tablename__ = "isp_invoices"

    id             = Column(String(36), primary_key=True, default=_uuid)
    org_id         = Column(String(36), ForeignKey("organizations.id"), nullable=False, index=True)
    invoice_number = Column(String(30), unique=True, nullable=False)
    amount         = Column(Numeric(10, 2), nullable=False)
    status         = Column(String(20), nullable=False, default="pending")
    due_date       = Column(DateTime(timezone=True), nullable=False)
    paid_at        = Column(DateTime(timezone=True), nullable=True)
    mpesa_ref      = Column(String(100), nullable=True)
    created_at     = Column(DateTime(timezone=True), nullable=False, default=_now)

    def __repr__(self): return f"<ISPInvoice {self.invoice_number} {self.status}>"
