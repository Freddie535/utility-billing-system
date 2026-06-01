from decimal import Decimal
from typing import List
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
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
from billing_system.api.frontend import router as frontend_router
from billing_system.security.routes import router as auth_router
from billing_system.security.isp_routes import router as isp_router
from billing_system.services.scheduler import start_scheduler
from billing_system.security.auth import get_current_user, create_user
from billing_system.security.models import UserRole

app = FastAPI(title="HotspotPro Billing System", version="2.0.0")

app.mount("/static", StaticFiles(directory="billing_system/static"), name="static")
app.include_router(auth_router)
app.include_router(isp_router)
app.include_router(frontend_router)


@app.on_event("startup")
def on_startup():
    init_db()
    # Create security tables
    from billing_system.models.models import Base
    from billing_system.security.models import User, AuditLog, BannedIP, LoginAttempt
    from billing_system.security.isp_models import Organization, ISPPackage, EmailVerification, ISPInvoice
    from billing_system.db.database import engine
    Base.metadata.create_all(bind=engine)
    # Create default admin if no users exist
    from billing_system.db.database import SessionLocal
    db = SessionLocal()
    try:
        existing = db.query(User).first()
        if not existing:
            user, msg = create_user(
                db,
                username="admin",
                email="admin@hotspotpro.com",
                full_name="System Administrator",
                password="Admin@1234!",
                role=UserRole.SUPER_ADMIN,
            )
            if user:
                db.commit()
                print("✅ Default admin created: admin / Admin@1234!")
            else:
                print(f"Admin creation failed: {msg}")
        else:
            print(f"✅ Admin already exists")
    except Exception as e:
        print(f"Startup error: {e}")
        db.rollback()
    finally:
        db.close()

    # Start automated billing scheduler
    try:
        start_scheduler()
        print("✅ Automated billing scheduler started")
    except Exception as e:
        print(f"Scheduler error: {e}")


# ── Protect all frontend routes ───────────────

def require_login(request: Request, db: Session = Depends(get_db_dep)):
    token = request.cookies.get("access_token")
    if not token:
        return None
    return get_current_user(db, token)


@app.middleware("http")
async def auth_middleware(request, call_next):
    # Public routes that don't need login
    public_routes = [
        "/auth/login",
        "/auth/logout",
        "/static/",
        "/health",
        "/docs",
        "/openapi.json",
        "/redoc",
    ]
    path = request.url.path
    is_public = any(path.startswith(r) for r in public_routes)
    if not is_public:
        token = request.cookies.get("access_token")
        if not token:
            return RedirectResponse("/auth/login", status_code=303)
    response = await call_next(request)
    return response


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
