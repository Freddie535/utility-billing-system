from decimal import Decimal
from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from billing_system.db.database import get_db_dep
from billing_system.models.models import (
    Customer, Invoice, Payment, TariffPlan,
    InvoiceStatus, PaymentMethod, PaymentStatus
)
from billing_system.services.billing_service import BillingService

router = APIRouter()

def get_org_id(request: Request, db) -> str:
    """Get the org_id for the current logged in ISP."""
    from billing_system.security.auth import get_current_user
    from billing_system.security.isp_models import Organization
    token = request.cookies.get("access_token")
    if not token:
        return None
    user = get_current_user(db, token)
    if not user:
        return None
    org = db.query(Organization).filter_by(owner_id=user.id).first()
    return org.id if org else None
templates = Jinja2Templates(directory="billing_system/templates")

@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db_dep)):
    org_id = get_org_id(request, db)
    if org_id:
        total_customers = db.query(Customer).filter_by(org_id=org_id).count()
        total_invoices  = db.query(Invoice).filter_by(org_id=org_id).count()
        unpaid_invoices = db.query(Invoice).filter(
            Invoice.org_id == org_id,
            Invoice.status.in_([InvoiceStatus.ISSUED, InvoiceStatus.OVERDUE])
        ).count()
        confirmed_payments = db.query(Payment).filter_by(status=PaymentStatus.CONFIRMED).all()
        org_invoice_ids = [i.id for i in db.query(Invoice).filter_by(org_id=org_id).all()]
        confirmed_payments = [p for p in confirmed_payments if p.invoice_id in org_invoice_ids]
        recent_customers = db.query(Customer).filter_by(org_id=org_id).order_by(
            Customer.created_at.desc()).limit(5).all()
    else:
        total_customers = db.query(Customer).count()
        total_invoices  = db.query(Invoice).count()
        unpaid_invoices = db.query(Invoice).filter(
            Invoice.status.in_([InvoiceStatus.ISSUED, InvoiceStatus.OVERDUE])
        ).count()
        confirmed_payments = db.query(Payment).filter_by(status=PaymentStatus.CONFIRMED).all()
        recent_customers = db.query(Customer).order_by(Customer.created_at.desc()).limit(5).all()
    total_revenue = sum(p.amount for p in confirmed_payments)
    from fastapi.responses import HTMLResponse
    from jinja2 import Environment, FileSystemLoader
    env = Environment(loader=FileSystemLoader("billing_system/templates"))
    t = env.get_template("dashboard.html")
    html = t.render(
        request=request,
        active="dashboard",
        total_customers=total_customers,
        total_invoices=total_invoices,
        total_revenue=f"{total_revenue:.2f}",
        unpaid_invoices=unpaid_invoices,
        recent_customers=recent_customers,
    )
    return HTMLResponse(html)

@router.get("/customers", response_class=HTMLResponse)
def customers_page(request: Request, db: Session = Depends(get_db_dep)):
    org_id = get_org_id(request, db)
    if org_id:
        customers = db.query(Customer).filter_by(org_id=org_id).order_by(Customer.created_at.desc()).all()
    else:
        customers = db.query(Customer).order_by(Customer.created_at.desc()).all()
    from jinja2 import Environment, FileSystemLoader
    from fastapi.responses import HTMLResponse
    env = Environment(loader=FileSystemLoader("billing_system/templates"))
    html = env.get_template("customers.html").render(request=request, active="customers", customers=customers)
    return HTMLResponse(html)

@router.post("/customers/new")
def add_customer(
    request: Request,
    account_number: str = Form(...),
    full_name: str = Form(...),
    phone: str = Form(""),
    email: str = Form(""),
    address: str = Form(""),
    db: Session = Depends(get_db_dep),
):
    try:
        org_id = get_org_id(request, db)
        customer = BillingService.create_customer(
            db,
            account_number=account_number,
            full_name=full_name,
            phone=phone or None,
            email=email or None,
            address=address or None,
        )
        if org_id:
            customer.org_id = org_id
            db.flush()
        customers = db.query(Customer).order_by(Customer.created_at.desc()).all()
        from jinja2 import Environment, FileSystemLoader
        from fastapi.responses import HTMLResponse
        env = Environment(loader=FileSystemLoader("billing_system/templates"))
        html = env.get_template("customers.html").render(request=request, active="customers", customers=customers, message=f"Customer {full_name} added successfully!")
        return HTMLResponse(html)
    except Exception as e:
        customers = db.query(Customer).order_by(Customer.created_at.desc()).all()
        from jinja2 import Environment, FileSystemLoader
        from fastapi.responses import HTMLResponse
        env = Environment(loader=FileSystemLoader("billing_system/templates"))
        html = env.get_template("customers.html").render(request=request, active="customers", customers=customers, error=str(e))
        return HTMLResponse(html)

@router.get("/packages", response_class=HTMLResponse)
def packages_page(request: Request, db: Session = Depends(get_db_dep)):
    plans = db.query(TariffPlan).filter_by(is_active=True).all()
    from jinja2 import Environment, FileSystemLoader
    from fastapi.responses import HTMLResponse
    env = Environment(loader=FileSystemLoader("billing_system/templates"))
    html = env.get_template("packages.html").render(request=request, active="packages", plans=plans)
    return HTMLResponse(html)

@router.get("/invoices", response_class=HTMLResponse)
def invoices_page(request: Request, db: Session = Depends(get_db_dep)):
    org_id = get_org_id(request, db)
    invoices = []
    query = db.query(Invoice).filter_by(org_id=org_id) if org_id else db.query(Invoice)
    for inv in query.order_by(Invoice.created_at.desc()).all():
        c = db.query(Customer).filter_by(id=inv.customer_id).first()
        invoices.append({
            "id": inv.id,
            "invoice_number": inv.invoice_number,
            "customer_name": c.full_name if c else "—",
            "subtotal": inv.subtotal,
            "tax_amount": inv.tax_amount,
            "total_due": inv.total_due,
            "status": inv.status,
            "due_date": inv.due_date,
            "created_at": inv.created_at,
        })
    from jinja2 import Environment, FileSystemLoader
    from fastapi.responses import HTMLResponse
    env = Environment(loader=FileSystemLoader("billing_system/templates"))
    html = env.get_template("invoices.html").render(request=request, active="invoices", invoices=invoices)
    return HTMLResponse(html)

@router.post("/invoices/{invoice_id}/issue")
def issue_invoice_page(invoice_id: str, db: Session = Depends(get_db_dep)):
    try:
        BillingService.issue_invoice(db, invoice_id)
    except Exception:
        pass
    return RedirectResponse("/invoices", status_code=303)

@router.get("/payments", response_class=HTMLResponse)
def payments_page(
    request: Request,
    invoice_id: str = None,
    db: Session = Depends(get_db_dep),
):
    org_id = get_org_id(request, db)
    payments = []
    pay_query = db.query(Payment).order_by(Payment.created_at.desc())
    for p in pay_query.all():
        c   = db.query(Customer).filter_by(id=p.customer_id).first()
        inv = db.query(Invoice).filter_by(id=p.invoice_id).first()
        payments.append({
            "reference": p.reference,
            "customer_name": c.full_name if c else "—",
            "invoice_number": inv.invoice_number if inv else "—",
            "amount": p.amount,
            "method": p.method,
            "status": p.status,
            "paid_at": p.paid_at,
        })
    issued_invoices = []
    for inv in db.query(Invoice).filter(Invoice.status == InvoiceStatus.ISSUED).all():
        c = db.query(Customer).filter_by(id=inv.customer_id).first()
        issued_invoices.append({
            "id": inv.id,
            "invoice_number": inv.invoice_number,
            "customer_name": c.full_name if c else "—",
            "total_due": inv.total_due,
        })
    from jinja2 import Environment, FileSystemLoader
    from fastapi.responses import HTMLResponse
    env = Environment(loader=FileSystemLoader("billing_system/templates"))
    html = env.get_template("payments.html").render(request=request, active="payments", payments=payments, issued_invoices=issued_invoices, selected_invoice_id=invoice_id)
    return HTMLResponse(html)

@router.post("/payments/new")
def record_payment_page(
    request: Request,
    invoice_id: str = Form(...),
    amount: str = Form(...),
    method: str = Form(...),
    reference: str = Form(""),
    db: Session = Depends(get_db_dep),
):
    try:
        method_map = {
            "mpesa": PaymentMethod.MPESA,
            "bank_transfer": PaymentMethod.BANK_TRANSFER,
            "cash": PaymentMethod.CASH,
            "card": PaymentMethod.CARD,
        }
        BillingService.record_payment(
            db,
            invoice_id=invoice_id,
            amount=Decimal(amount),
            method=method_map[method],
            reference=reference or None,
        )
    except Exception:
        pass
    return RedirectResponse("/payments", status_code=303)
