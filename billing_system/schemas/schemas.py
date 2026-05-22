from __future__ import annotations
from datetime import datetime
from decimal import Decimal
from typing import Optional, List
from pydantic import BaseModel, Field
from billing_system.models.models import (
    TariffType, InvoiceStatus, PaymentMethod, PaymentStatus, CustomerStatus, MeterStatus)

class OkResponse(BaseModel):
    ok: bool = True
    message: str = "success"

class CustomerCreate(BaseModel):
    account_number: str = Field(..., min_length=3, max_length=20)
    full_name: str = Field(..., min_length=2)
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None

class CustomerOut(BaseModel):
    id: str
    account_number: str
    full_name: str
    email: Optional[str]
    phone: Optional[str]
    address: Optional[str]
    status: CustomerStatus
    credit_balance: Decimal
    created_at: datetime
    model_config = {"from_attributes": True}

class TariffTierIn(BaseModel):
    tier_order: int = Field(..., ge=1)
    units_from: Decimal = Field(..., ge=0)
    units_to: Optional[Decimal] = None
    rate: Decimal = Field(..., gt=0)
    description: Optional[str] = None

class TariffPlanCreate(BaseModel):
    name: str
    tariff_type: TariffType
    currency: str = "KES"
    standing_charge: Decimal = Decimal("0")
    tiers: List[TariffTierIn]
    description: Optional[str] = None

class TariffTierOut(TariffTierIn):
    id: str
    plan_id: str
    model_config = {"from_attributes": True}

class TariffPlanOut(BaseModel):
    id: str
    name: str
    tariff_type: TariffType
    currency: str
    standing_charge: Decimal
    is_active: bool
    tiers: List[TariffTierOut]
    description: Optional[str]
    model_config = {"from_attributes": True}

class MeterInstall(BaseModel):
    serial_number: str = Field(..., min_length=3)
    tariff_plan_id: str
    unit: str = "session"
    multiplier: Decimal = Decimal("1.0")
    initial_reading: Decimal = Decimal("0")

class MeterOut(BaseModel):
    id: str
    customer_id: str
    serial_number: str
    unit: str
    multiplier: Decimal
    tariff_plan_id: str
    status: MeterStatus
    last_read_value: Optional[Decimal]
    last_read_at: Optional[datetime]
    model_config = {"from_attributes": True}

class ReadingCreate(BaseModel):
    reading_value: Decimal = Field(..., ge=0)
    read_at: Optional[datetime] = None
    source: str = "manual"
    notes: Optional[str] = None
    is_estimated: bool = False

class UsageRecordOut(BaseModel):
    id: str
    meter_id: str
    billing_cycle_id: Optional[str]
    reading_value: Decimal
    previous_value: Decimal
    consumption: Decimal
    read_at: datetime
    source: str
    is_estimated: bool
    model_config = {"from_attributes": True}

class BillingCycleCreate(BaseModel):
    period_start: datetime
    period_end: datetime

class BillingCycleOut(BaseModel):
    id: str
    customer_id: str
    period_start: datetime
    period_end: datetime
    is_closed: bool
    closed_at: Optional[datetime]
    model_config = {"from_attributes": True}

class GenerateInvoiceRequest(BaseModel):
    billing_cycle_id: str
    tax_rate: Decimal = Decimal("0.16")
    due_days: int = 30
    apply_credit: bool = True

class LineItemOut(BaseModel):
    id: str
    description: str
    quantity: Decimal
    unit: Optional[str]
    unit_rate: Decimal
    amount: Decimal
    sort_order: int
    model_config = {"from_attributes": True}

class InvoiceOut(BaseModel):
    id: str
    invoice_number: str
    customer_id: str
    billing_cycle_id: str
    status: InvoiceStatus
    currency: str
    subtotal: Decimal
    tax_amount: Decimal
    credit_applied: Decimal
    total_due: Decimal
    due_date: Optional[datetime]
    issued_at: Optional[datetime]
    paid_at: Optional[datetime]
    line_items: List[LineItemOut] = []
    model_config = {"from_attributes": True}

class PaymentCreate(BaseModel):
    amount: Decimal = Field(..., gt=0)
    method: PaymentMethod
    reference: Optional[str] = None
    paid_at: Optional[datetime] = None

class PaymentOut(BaseModel):
    id: str
    invoice_id: str
    customer_id: str
    amount: Decimal
    currency: str
    method: PaymentMethod
    status: PaymentStatus
    reference: Optional[str]
    paid_at: Optional[datetime]
    model_config = {"from_attributes": True}
