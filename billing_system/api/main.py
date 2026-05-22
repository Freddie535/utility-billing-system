from decimal import Decimal
from typing import List
from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from billing_system.db.database import get_db_dep, init_db
from billing_system.models.models import (
    Customer, Meter, TariffPlan, BillingCycle, Invoice, UsageRecord, Payment)
from billing_system.services.billing_service import BillingService
from billing_system.schemas.schemas import (
    CustomerCreate, CustomerOut,
    TariffPlanCreate, TariffPlanOut,
    MeterInstall, MeterOut,
    ReadingCreate, UsageRecordOut,
    BillingCycleCreate, BillingCycleOut,
    GenerateInvoiceRequest, InvoiceOut,
    PaymentCreate, PaymentOut,
)

app = FastAPI(title="Utility Billing System", version="1.0.0")

@app.on_event("startup")
def on_startup():
    init_db()

@app.get("/health", tags=["system"])
def health():
    return {"status": "ok"}

@app.post("/customers", response_model=CustomerOut, status_code=201, tags=["customers"])
def create_customer(body: CustomerCreate, db: Session = Depends(get_db_dep)):
    return BillingService.create_customer(db, **body.model_dump())

@app.get("/customers/{customer_id}", response_model=CustomerOut, tags=["customers"])
def get_customer(customer_id: str, db: Session = Depends(get_db_dep)):
    c = db.query(Customer).filter_by(id=customer_id).first()
    if not c:
        raise HTTPException(404, "Customer not found")
    return c

@app.get("/customers", response_model=List[CustomerOut], tags=["customers"])
def list_customers(skip: int = 0, limit: int = 50, db: Session = Depends(get_db_dep)):
    return db.query(Customer).offset(skip).limit(limit).all()

@app.post("/tariffs", response_model=TariffPlanOut, status_code=201, tags=["tariffs"])
def create_tariff(body: TariffPlanCreate, db: Session = Depends(get_db_dep)):
    return BillingService.create_tariff_plan(
        db, name=body.name, tariff_type=body.tariff_type,
        currency=body.currency, standing_charge=body.standing_charge,
        tiers=[t.model_dump() for t in body.tiers], description=body.description)

@app.get("/tariffs/{plan_id}", response_model=TariffPlanOut, tags=["tariffs"])
def get_tariff(plan_id: str, db: Session = Depends(get_db_dep)):
    p = db.query(TariffPlan).filter_by(id=plan_id).first()
    if not p:
        raise HTTPException(404, "Tariff plan not found")
    return p

@app.get("/tariffs", response_model=List[TariffPlanOut], tags=["tariffs"])
def list_tariffs(db: Session = Depends(get_db_dep)):
    return db.query(TariffPlan).filter_by(is_active=True).all()

@app.post("/customers/{customer_id}/meters", response_model=MeterOut, status_code=201, tags=["meters"])
def install_meter(customer_id: str, body: MeterInstall, db: Session = Depends(get_db_dep)):
    if not db.query(Customer).filter_by(id=customer_id).first():
        raise HTTPException(404, "Customer not found")
    return BillingService.install_meter(db, customer_id=customer_id, **body.model_dump())

@app.get("/customers/{customer_id}/meters", response_model=List[MeterOut], tags=["meters"])
def list_meters(customer_id: str, db: Session = Depends(get_db_dep)):
    return db.query(Meter).filter_by(customer_id=customer_id).all()

@app.get("/meters/{meter_id}", response_model=MeterOut, tags=["meters"])
def get_meter(meter_id: str, db: Session = Depends(get_db_dep)):
    m = db.query(Meter).filter_by(id=meter_id).first()
    if not m:
        raise HTTPException(404, "Meter not found")
    return m

@app.post("/meters/{meter_id}/readings", response_model=UsageRecordOut, status_code=201, tags=["usage"])
def record_reading(meter_id: str, body: ReadingCreate, db: Session = Depends(get_db_dep)):
    try:
        return BillingService.record_reading(db, meter_id=meter_id, **body.model_dump())
    except ValueError as e:
        raise HTTPException(422, str(e))

@app.get("/meters/{meter_id}/readings", response_model=List[UsageRecordOut], tags=["usage"])
def get_readings(meter_id: str, skip: int = 0, limit: int = 100, db: Session = Depends(get_db_dep)):
    return db.query(UsageRecord).filter_by(meter_id=meter_id).order_by(
        UsageRecord.read_at.desc()).offset(skip).limit(limit).all()

@app.patch("/readings/{reading_id}/assign-cycle/{cycle_id}", response_model=UsageRecordOut, tags=["usage"])
def assign_reading_to_cycle(reading_id: str, cycle_id: str, db: Session = Depends(get_db_dep)):
    rec = db.query(UsageRecord).filter_by(id=reading_id).first()
    if not rec:
        raise HTTPException(404, "Reading not found")
    rec.billing_cycle_id = cycle_id
    db.flush()
    return rec

@app.post("/customers/{customer_id}/cycles", response_model=BillingCycleOut, status_code=201, tags=["billing"])
def open_cycle(customer_id: str, body: BillingCycleCreate, db: Session = Depends(get_db_dep)):
    return BillingService.open_billing_cycle(
        db, customer_id=customer_id,
        period_start=body.period_start,
        period_end=body.period_end)

@app.post("/cycles/{cycle_id}/close", response_model=BillingCycleOut, tags=["billing"])
def close_cycle(cycle_id: str, db: Session = Depends(get_db_dep)):
    try:
        return BillingService.close_billing_cycle(db, cycle_id)
    except ValueError as e:
        raise HTTPException(422, str(e))

@app.get("/customers/{customer_id}/cycles", response_model=List[BillingCycleOut], tags=["billing"])
def list_cycles(customer_id: str, db: Session = Depends(get_db_dep)):
    return db.query(BillingCycle).filter_by(customer_id=customer_id).all()

@app.post("/invoices/generate", response_model=InvoiceOut, status_code=201, tags=["invoices"])
def generate_invoice(body: GenerateInvoiceRequest, db: Session = Depends(get_db_dep)):
    try:
        return BillingService.generate_invoice(
            db, billing_cycle_id=body.billing_cycle_id,
            tax_rate=body.tax_rate, due_days=body.due_days,
            apply_credit=body.apply_credit)
    except Exception as e:
        raise HTTPException(422, str(e))

@app.post("/invoices/{invoice_id}/issue", response_model=InvoiceOut, tags=["invoices"])
def issue_invoice(invoice_id: str, db: Session = Depends(get_db_dep)):
    try:
        return BillingService.issue_invoice(db, invoice_id)
    except ValueError as e:
        raise HTTPException(422, str(e))

@app.post("/invoices/{invoice_id}/void", response_model=InvoiceOut, tags=["invoices"])
def void_invoice(invoice_id: str, reason: str = None, db: Session = Depends(get_db_dep)):
    try:
        return BillingService.void_invoice(db, invoice_id, reason)
    except ValueError as e:
        raise HTTPException(422, str(e))

@app.get("/invoices/{invoice_id}", response_model=InvoiceOut, tags=["invoices"])
def get_invoice(invoice_id: str, db: Session = Depends(get_db_dep)):
    inv = db.query(Invoice).filter_by(id=invoice_id).first()
    if not inv:
        raise HTTPException(404, "Invoice not found")
    return inv

@app.get("/customers/{customer_id}/invoices", response_model=List[InvoiceOut], tags=["invoices"])
def list_invoices(customer_id: str, db: Session = Depends(get_db_dep)):
    return db.query(Invoice).filter_by(customer_id=customer_id).order_by(
        Invoice.created_at.desc()).all()

@app.post("/invoices/{invoice_id}/payments", response_model=PaymentOut, status_code=201, tags=["payments"])
def record_payment(invoice_id: str, body: PaymentCreate, db: Session = Depends(get_db_dep)):
    try:
        return BillingService.record_payment(
            db, invoice_id=invoice_id, **body.model_dump())
    except ValueError as e:
        raise HTTPException(422, str(e))

@app.get("/invoices/{invoice_id}/payments", response_model=List[PaymentOut], tags=["payments"])
def list_payments(invoice_id: str, db: Session = Depends(get_db_dep)):
    return db.query(Payment).filter_by(invoice_id=invoice_id).all()
