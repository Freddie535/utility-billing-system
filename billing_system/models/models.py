import uuid
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum as PyEnum

from sqlalchemy import (
    Column, String, Numeric, Integer, Boolean, DateTime,
    ForeignKey, Enum, Text, UniqueConstraint, Index, CheckConstraint,
)
from sqlalchemy.orm import relationship, declarative_base

Base = declarative_base()

def _uuid(): return str(uuid.uuid4())
def _now():  return datetime.now(timezone.utc)

class CustomerStatus(PyEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    CLOSED = "closed"

class MeterStatus(PyEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    REMOVED = "removed"

class TariffType(PyEnum):
    FLAT = "flat"
    TIERED = "tiered"
    BLOCK = "block"

class InvoiceStatus(PyEnum):
    DRAFT = "draft"
    ISSUED = "issued"
    PAID = "paid"
    OVERDUE = "overdue"
    VOID = "void"

class PaymentMethod(PyEnum):
    BANK_TRANSFER = "bank_transfer"
    MPESA = "mpesa"
    CARD = "card"
    CASH = "cash"

class PaymentStatus(PyEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    FAILED = "failed"
    REVERSED = "reversed"


class Customer(Base):
    __tablename__ = "customers"
    id             = Column(String(36), primary_key=True, default=_uuid)
    account_number = Column(String(20), unique=True, nullable=False, index=True)
    full_name      = Column(String(255), nullable=False)
    email          = Column(String(255), unique=True, nullable=True)
    phone          = Column(String(30), nullable=True)
    address        = Column(Text, nullable=True)
    status         = Column(Enum(CustomerStatus), nullable=False, default=CustomerStatus.ACTIVE)
    credit_balance = Column(Numeric(14, 4), nullable=False, default=Decimal("0.0000"))
    created_at     = Column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at     = Column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)
    meters         = relationship("Meter", back_populates="customer", cascade="all, delete-orphan")
    billing_cycles = relationship("BillingCycle", back_populates="customer")
    def __repr__(self): return f"<Customer {self.account_number} - {self.full_name}>"


class Meter(Base):
    __tablename__ = "meters"
    id              = Column(String(36), primary_key=True, default=_uuid)
    customer_id     = Column(String(36), ForeignKey("customers.id"), nullable=False, index=True)
    serial_number   = Column(String(60), unique=True, nullable=False, index=True)
    unit            = Column(String(20), nullable=False, default="session")
    multiplier      = Column(Numeric(10, 6), nullable=False, default=Decimal("1.0"))
    tariff_plan_id  = Column(String(36), ForeignKey("tariff_plans.id"), nullable=False)
    status          = Column(Enum(MeterStatus), nullable=False, default=MeterStatus.ACTIVE)
    installed_at    = Column(DateTime(timezone=True), nullable=True)
    last_read_at    = Column(DateTime(timezone=True), nullable=True)
    last_read_value = Column(Numeric(18, 6), nullable=True)
    created_at      = Column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at      = Column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)
    customer        = relationship("Customer", back_populates="meters")
    tariff_plan     = relationship("TariffPlan", back_populates="meters")
    usage_records   = relationship("UsageRecord", back_populates="meter", cascade="all, delete-orphan")
    def __repr__(self): return f"<Meter {self.serial_number} ({self.unit})>"


class TariffPlan(Base):
    __tablename__ = "tariff_plans"
    id              = Column(String(36), primary_key=True, default=_uuid)
    name            = Column(String(100), nullable=False)
    description     = Column(Text, nullable=True)
    tariff_type     = Column(Enum(TariffType), nullable=False, default=TariffType.FLAT)
    currency        = Column(String(3), nullable=False, default="KES")
    standing_charge = Column(Numeric(14, 4), nullable=False, default=Decimal("0.0"))
    is_active       = Column(Boolean, nullable=False, default=True)
    effective_from  = Column(DateTime(timezone=True), nullable=False, default=_now)
    effective_to    = Column(DateTime(timezone=True), nullable=True)
    created_at      = Column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at      = Column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)
    tiers           = relationship("TariffTier", back_populates="plan",
                                   order_by="TariffTier.tier_order", cascade="all, delete-orphan")
    meters          = relationship("Meter", back_populates="tariff_plan")
    def __repr__(self): return f"<TariffPlan {self.name}>"


class TariffTier(Base):
    __tablename__ = "tariff_tiers"
    id          = Column(String(36), primary_key=True, default=_uuid)
    plan_id     = Column(String(36), ForeignKey("tariff_plans.id"), nullable=False, index=True)
    tier_order  = Column(Integer, nullable=False)
    units_from  = Column(Numeric(18, 6), nullable=False, default=Decimal("0"))
    units_to    = Column(Numeric(18, 6), nullable=True)
    rate        = Column(Numeric(14, 6), nullable=False)
    description = Column(String(200), nullable=True)
    plan        = relationship("TariffPlan", back_populates="tiers")
    __table_args__ = (
        UniqueConstraint("plan_id", "tier_order", name="uq_plan_tier_order"),
        CheckConstraint("units_from >= 0", name="ck_units_from_positive"),
        CheckConstraint("units_to IS NULL OR units_to > units_from", name="ck_units_range"),
    )
    def __repr__(self): return f"<Tier {self.tier_order} @ {self.rate}>"


class UsageRecord(Base):
    __tablename__ = "usage_records"
    id               = Column(String(36), primary_key=True, default=_uuid)
    meter_id         = Column(String(36), ForeignKey("meters.id"), nullable=False, index=True)
    billing_cycle_id = Column(String(36), ForeignKey("billing_cycles.id"), nullable=True, index=True)
    reading_value    = Column(Numeric(18, 6), nullable=False)
    previous_value   = Column(Numeric(18, 6), nullable=False)
    consumption      = Column(Numeric(18, 6), nullable=False)
    read_at          = Column(DateTime(timezone=True), nullable=False)
    source           = Column(String(40), nullable=False, default="manual")
    notes            = Column(Text, nullable=True)
    is_estimated     = Column(Boolean, nullable=False, default=False)
    created_at       = Column(DateTime(timezone=True), nullable=False, default=_now)
    meter            = relationship("Meter", back_populates="usage_records")
    billing_cycle    = relationship("BillingCycle", back_populates="usage_records")
    __table_args__   = (Index("ix_usage_meter_read_at", "meter_id", "read_at"),)
    def __repr__(self): return f"<UsageRecord {self.consumption} @ {self.read_at}>"


class BillingCycle(Base):
    __tablename__ = "billing_cycles"
    id           = Column(String(36), primary_key=True, default=_uuid)
    customer_id  = Column(String(36), ForeignKey("customers.id"), nullable=False, index=True)
    period_start = Column(DateTime(timezone=True), nullable=False)
    period_end   = Column(DateTime(timezone=True), nullable=False)
    is_closed    = Column(Boolean, nullable=False, default=False)
    closed_at    = Column(DateTime(timezone=True), nullable=True)
    created_at   = Column(DateTime(timezone=True), nullable=False, default=_now)
    customer      = relationship("Customer", back_populates="billing_cycles")
    usage_records = relationship("UsageRecord", back_populates="billing_cycle")
    invoices      = relationship("Invoice", back_populates="billing_cycle")
    __table_args__ = (
        UniqueConstraint("customer_id", "period_start", name="uq_customer_period"),
        CheckConstraint("period_end > period_start", name="ck_period_range"),
    )
    def __repr__(self): return f"<BillingCycle {self.period_start} to {self.period_end}>"


class Invoice(Base):
    __tablename__ = "invoices"
    id               = Column(String(36), primary_key=True, default=_uuid)
    invoice_number   = Column(String(30), unique=True, nullable=False, index=True)
    customer_id      = Column(String(36), ForeignKey("customers.id"), nullable=False, index=True)
    billing_cycle_id = Column(String(36), ForeignKey("billing_cycles.id"), nullable=False)
    status           = Column(Enum(InvoiceStatus), nullable=False, default=InvoiceStatus.DRAFT)
    currency         = Column(String(3), nullable=False, default="KES")
    subtotal         = Column(Numeric(14, 4), nullable=False, default=Decimal("0.0"))
    tax_amount       = Column(Numeric(14, 4), nullable=False, default=Decimal("0.0"))
    credit_applied   = Column(Numeric(14, 4), nullable=False, default=Decimal("0.0"))
    total_due        = Column(Numeric(14, 4), nullable=False, default=Decimal("0.0"))
    due_date         = Column(DateTime(timezone=True), nullable=True)
    issued_at        = Column(DateTime(timezone=True), nullable=True)
    paid_at          = Column(DateTime(timezone=True), nullable=True)
    notes            = Column(Text, nullable=True)
    created_at       = Column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at       = Column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)
    billing_cycle = relationship("BillingCycle", back_populates="invoices")
    line_items    = relationship("InvoiceLineItem", back_populates="invoice",
                                 cascade="all, delete-orphan", order_by="InvoiceLineItem.sort_order")
    payments      = relationship("Payment", back_populates="invoice")
    def __repr__(self): return f"<Invoice {self.invoice_number} {self.status.value} {self.total_due}>"


class InvoiceLineItem(Base):
    __tablename__ = "invoice_line_items"
    id          = Column(String(36), primary_key=True, default=_uuid)
    invoice_id  = Column(String(36), ForeignKey("invoices.id"), nullable=False, index=True)
    meter_id    = Column(String(36), ForeignKey("meters.id"), nullable=True)
    description = Column(String(255), nullable=False)
    quantity    = Column(Numeric(18, 6), nullable=False, default=Decimal("1"))
    unit        = Column(String(20), nullable=True)
    unit_rate   = Column(Numeric(14, 6), nullable=False, default=Decimal("0"))
    amount      = Column(Numeric(14, 4), nullable=False)
    sort_order  = Column(Integer, nullable=False, default=0)
    invoice     = relationship("Invoice", back_populates="line_items")
    def __repr__(self): return f"<LineItem {self.description} {self.amount}>"


class Payment(Base):
    __tablename__ = "payments"
    id          = Column(String(36), primary_key=True, default=_uuid)
    invoice_id  = Column(String(36), ForeignKey("invoices.id"), nullable=False, index=True)
    customer_id = Column(String(36), ForeignKey("customers.id"), nullable=False, index=True)
    amount      = Column(Numeric(14, 4), nullable=False)
    currency    = Column(String(3), nullable=False, default="KES")
    method      = Column(Enum(PaymentMethod), nullable=False)
    status      = Column(Enum(PaymentStatus), nullable=False, default=PaymentStatus.PENDING)
    reference   = Column(String(100), nullable=True)
    paid_at     = Column(DateTime(timezone=True), nullable=True)
    created_at  = Column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at  = Column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)
    invoice     = relationship("Invoice", back_populates="payments")
    __table_args__ = (CheckConstraint("amount > 0", name="ck_payment_positive"),)
    def __repr__(self): return f"<Payment {self.reference} {self.amount}>"
