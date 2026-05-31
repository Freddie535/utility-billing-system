"""
ISP Registration and Setup Routes
===================================
/isp/register     - Registration page
/isp/verify-email - Email verification
/isp/setup        - Account setup
/isp/dashboard    - ISP dashboard
"""
import json
import re
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from jinja2 import Environment, FileSystemLoader
from sqlalchemy.orm import Session

from billing_system.db.database import get_db_dep
from billing_system.security.auth import create_user, get_current_user
from billing_system.security.models import User, UserRole
from billing_system.security.isp_models import (
    Organization, ISPPackage, EmailVerification,
    SubscriptionPlan, ISPStatus
)
from billing_system.security.email_service import (
    create_verification_token,
    verify_email_token,
    send_verification_email,
    send_welcome_email,
)

router = APIRouter(prefix="/isp")


def render(template_name: str, **kwargs) -> HTMLResponse:
    env = Environment(loader=FileSystemLoader("billing_system/templates"))
    html = env.get_template(template_name).render(**kwargs)
    return HTMLResponse(html)


def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_-]+', '-', text)
    return text[:50]


def get_current_user_from_cookie(request: Request, db: Session):
    token = request.cookies.get("access_token")
    if not token:
        return None
    return get_current_user(db, token)


# ── Registration ──────────────────────────────

@router.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    return render("isp_register.html", form={})


@router.post("/register")
async def register(
    request: Request,
    db: Session = Depends(get_db_dep),
):
    form_data = await request.form()
    company_name   = form_data.get("company_name", "").strip()
    email          = form_data.get("email", "").strip()
    helpline       = form_data.get("helpline", "").strip()
    full_name      = form_data.get("full_name", "").strip()
    username       = form_data.get("username", "").strip()
    login_email    = form_data.get("login_email", "").strip()
    password       = form_data.get("password", "")
    confirm_pass   = form_data.get("confirm_password", "")
    plan_str       = form_data.get("plan", "starter")

    form = {
        "company_name": company_name,
        "email": email,
        "helpline": helpline,
        "full_name": full_name,
        "username": username,
        "login_email": login_email,
        "plan": plan_str,
    }

    # Validation
    if not all([company_name, email, full_name, username, login_email, password]):
        return render("isp_register.html", error="All fields are required.", form=form)

    if password != confirm_pass:
        return render("isp_register.html", error="Passwords do not match.", form=form)

    if len(password) < 8:
        return render("isp_register.html",
                      error="Password must be at least 8 characters.", form=form)

    # Check if username/email taken
    existing = db.query(User).filter(
        (User.username == username) | (User.email == login_email)
    ).first()
    if existing:
        return render("isp_register.html",
                      error="Username or email already exists.", form=form)

    # Check company name taken
    existing_org = db.query(Organization).filter_by(
        company_name=company_name).first()
    if existing_org:
        return render("isp_register.html",
                      error="A company with this name already exists.", form=form)

    # Plan config
    plan_map = {
        "starter": (SubscriptionPlan.STARTER, 50,  1500),
        "growth":  (SubscriptionPlan.GROWTH,  200, 3500),
        "pro":     (SubscriptionPlan.PRO,      9999, 8000),
    }
    plan, max_customers, monthly_fee = plan_map.get(
        plan_str, plan_map["starter"])

    # Create user
    user, msg = create_user(
        db,
        username=username,
        email=login_email,
        full_name=full_name,
        password=password,
        role=UserRole.ISP_OWNER,
    )
    if not user:
        return render("isp_register.html", error=msg, form=form)

    # Create organization
    slug = slugify(company_name)
    existing_slug = db.query(Organization).filter_by(slug=slug).first()
    if existing_slug:
        slug = f"{slug}-{username}"

    org = Organization(
        company_name=company_name,
        slug=slug,
        owner_id=user.id,
        email=email,
        helpline=helpline or None,
        subscription_plan=plan,
        status=ISPStatus.PENDING,
        max_customers=max_customers,
        monthly_fee=Decimal(str(monthly_fee)),
        trial_ends_at=datetime.now(timezone.utc) + timedelta(days=30),
    )
    db.add(org)
    db.flush()

    # Create verification token
    token = create_verification_token(db, user.id, login_email)
    db.commit()

    # Send verification email
    send_verification_email(login_email, company_name, token)

    return render("isp_verify_pending.html", email=login_email)


# ── Email Verification ────────────────────────

@router.get("/verify-email/{token}")
def verify_email(token: str, db: Session = Depends(get_db_dep)):
    verification, error = verify_email_token(db, token)
    if error:
        return render("isp_register.html",
                      error=error, form={})

    # Activate user
    user = db.query(User).filter_by(id=verification.user_id).first()
    if not user:
        return render("isp_register.html",
                      error="User not found.", form={})

    user.is_active = True

    # Activate organization
    org = db.query(Organization).filter_by(owner_id=user.id).first()
    if org:
        org.status = ISPStatus.ACTIVE

    db.commit()

    # Send welcome email
    send_welcome_email(verification.email, org.company_name if org else "ISP", user.username)

    # Auto login
    from billing_system.security.auth import create_access_token
    token_jwt = create_access_token({"sub": user.id, "role": user.role.value})
    response = RedirectResponse("/isp/setup", status_code=303)
    response.set_cookie(
        key="access_token",
        value=token_jwt,
        httponly=True,
        max_age=60 * 60 * 8,
        samesite="lax",
        secure=False,
    )
    return response


# ── Setup ─────────────────────────────────────

@router.get("/setup", response_class=HTMLResponse)
def setup_page(request: Request, db: Session = Depends(get_db_dep)):
    user = get_current_user_from_cookie(request, db)
    if not user:
        return RedirectResponse("/auth/login", status_code=303)
    org = db.query(Organization).filter_by(owner_id=user.id).first()
    return render("isp_setup.html", org=org, user=user)


@router.post("/setup/save")
async def setup_save(
    request: Request,
    db: Session = Depends(get_db_dep),
):
    user = get_current_user_from_cookie(request, db)
    if not user:
        return RedirectResponse("/auth/login", status_code=303)

    form_data = await request.form()
    org = db.query(Organization).filter_by(owner_id=user.id).first()

    if org:
        org.company_name   = form_data.get("company_name", org.company_name)
        org.email          = form_data.get("email", org.email)
        org.helpline       = form_data.get("helpline", org.helpline)
        org.website        = form_data.get("website", org.website)
        org.address        = form_data.get("address", org.address)
        org.theme_primary  = form_data.get("theme_primary", org.theme_primary)
        org.theme_secondary= form_data.get("theme_secondary", org.theme_secondary)
        org.theme_bg       = form_data.get("theme_bg", org.theme_bg)
        org.theme_pattern  = form_data.get("theme_pattern", org.theme_pattern)

        # Save packages
        packages_json = form_data.get("packages", "[]")
        try:
            packages = json.loads(packages_json)
            # Delete old packages
            db.query(ISPPackage).filter_by(org_id=org.id).delete()
            # Add new ones (max 12)
            for i, pkg in enumerate(packages[:12]):
                db.add(ISPPackage(
                    org_id=org.id,
                    name=pkg["name"],
                    price=Decimal(str(pkg["price"])),
                    duration_hours=int(pkg["hours"]),
                    data_limit_mb=int(pkg["mb"]) if pkg.get("mb") else None,
                    speed_mbps=int(pkg["speed"]) if pkg.get("speed") else None,
                    is_streaming=pkg.get("streaming", False),
                    description=pkg.get("desc", ""),
                    sort_order=i,
                ))
        except Exception as e:
            print(f"Package save error: {e}")

        db.commit()

    return RedirectResponse("/isp/dashboard", status_code=303)


# ── ISP Dashboard ─────────────────────────────

@router.get("/dashboard", response_class=HTMLResponse)
def isp_dashboard(request: Request, db: Session = Depends(get_db_dep)):
    user = get_current_user_from_cookie(request, db)
    if not user:
        return RedirectResponse("/auth/login", status_code=303)

    org = db.query(Organization).filter_by(owner_id=user.id).first()
    if not org:
        return RedirectResponse("/isp/setup", status_code=303)

    packages = db.query(ISPPackage).filter_by(
        org_id=org.id, is_active=True).order_by(ISPPackage.sort_order).all()

    from billing_system.models.models import Customer, Invoice, Payment, PaymentStatus
    total_customers = db.query(Customer).count()
    total_invoices  = db.query(Invoice).count()
    confirmed_payments = db.query(Payment).filter_by(
        status=PaymentStatus.CONFIRMED).all()
    total_revenue = sum(p.amount for p in confirmed_payments)

    from jinja2 import Environment, FileSystemLoader
    env = Environment(loader=FileSystemLoader("billing_system/templates"))
    html = env.get_template("isp_dashboard.html").render(
        request=request,
        user=user,
        org=org,
        packages=packages,
        total_customers=total_customers,
        total_invoices=total_invoices,
        total_revenue=f"{total_revenue:.2f}",
    )
    return HTMLResponse(html)
