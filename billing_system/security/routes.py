"""
Auth Routes
===========
Login, logout, protect all dashboard pages
"""
from datetime import timedelta
from fastapi import APIRouter, Depends, Request, Form, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from jinja2 import Environment, FileSystemLoader
from sqlalchemy.orm import Session

from billing_system.db.database import get_db_dep
from billing_system.security.auth import (
    authenticate_user, create_access_token,
    get_current_user, is_ip_banned,
    check_and_ban_ip, audit, create_user
)
from billing_system.security.models import User, UserRole, AuditLog, BannedIP, LoginAttempt

router = APIRouter(prefix="/auth")


def render(template_name: str, **kwargs) -> HTMLResponse:
    env = Environment(loader=FileSystemLoader("billing_system/templates"))
    html = env.get_template(template_name).render(**kwargs)
    return HTMLResponse(html)


def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def get_current_user_from_cookie(request: Request, db: Session) -> User | None:
    token = request.cookies.get("access_token")
    if not token:
        return None
    return get_current_user(db, token)


# ── Login page ────────────────────────────────

@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return render("login.html")


@router.post("/login")
async def login(
    request: Request,
    response: Response,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db_dep),
):
    ip = get_client_ip(request)
    ua = request.headers.get("User-Agent", "")

    # Check if IP is banned
    if is_ip_banned(db, ip):
        audit(db, "login_blocked_banned_ip", details=f"Banned IP tried to login: {ip}",
              ip=ip, status="blocked")
        return render("login.html",
                      error="Access denied. Your IP has been blocked due to suspicious activity.",
                      username=username)

    # Check and possibly ban IP due to too many attempts
    if check_and_ban_ip(db, ip):
        return render("login.html",
                      error="Too many failed attempts. Your IP has been blocked for 24 hours.",
                      username=username)

    # Authenticate
    user, error = authenticate_user(db, username, password, ip, ua)

    if not user:
        return render("login.html", error=error, username=username)

    # Create JWT token
    token = create_access_token({"sub": user.id, "role": user.role.value})

    # Redirect based on role
    from billing_system.security.models import UserRole
    if user.role == UserRole.ISP_OWNER:
        redirect_url = "/isp/dashboard"
    else:
        redirect_url = "/"
    response = RedirectResponse(redirect_url, status_code=303)
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        max_age=60 * 60 * 8,
        samesite="lax",
        secure=False,
    )
    return response


# ── Logout ────────────────────────────────────

@router.get("/logout")
def logout(request: Request, db: Session = Depends(get_db_dep)):
    ip = get_client_ip(request)
    token = request.cookies.get("access_token")
    if token:
        user = get_current_user(db, token)
        if user:
            audit(db, "logout", user_id=user.id, ip=ip, status="success")
    response = RedirectResponse("/auth/login", status_code=303)
    response.delete_cookie("access_token")
    return response


# ── Security dashboard ────────────────────────

@router.get("/security", response_class=HTMLResponse)
def security_dashboard(request: Request, db: Session = Depends(get_db_dep)):
    user = get_current_user_from_cookie(request, db)
    if not user:
        return RedirectResponse("/auth/login", status_code=303)
    if user.role not in [UserRole.SUPER_ADMIN, UserRole.ADMIN]:
        return HTMLResponse("<h1>Access Denied</h1>", status_code=403)

    banned_ips   = db.query(BannedIP).order_by(BannedIP.created_at.desc()).limit(20).all()
    audit_logs   = db.query(AuditLog).order_by(AuditLog.created_at.desc()).limit(50).all()
    failed_logins = db.query(LoginAttempt).filter_by(success=False).order_by(
        LoginAttempt.created_at.desc()).limit(20).all()
    users        = db.query(User).all()

    from jinja2 import Environment, FileSystemLoader
    env = Environment(loader=FileSystemLoader("billing_system/templates"))
    html = env.get_template("security.html").render(
        request=request,
        active="security",
        current_user=user,
        banned_ips=banned_ips,
        audit_logs=audit_logs,
        failed_logins=failed_logins,
        users=users,
    )
    return HTMLResponse(html)


# ── Unban IP ──────────────────────────────────

@router.post("/unban/{ip_id}")
def unban_ip(ip_id: str, request: Request, db: Session = Depends(get_db_dep)):
    user = get_current_user_from_cookie(request, db)
    if not user or user.role not in [UserRole.SUPER_ADMIN, UserRole.ADMIN]:
        return RedirectResponse("/auth/login", status_code=303)
    ban = db.query(BannedIP).filter_by(id=ip_id).first()
    if ban:
        audit(db, "ip_unbanned", user_id=user.id,
              details=f"Unbanned IP: {ban.ip_address}",
              ip=get_client_ip(request), status="success")
        db.delete(ban)
    return RedirectResponse("/auth/security", status_code=303)


# ── Ban IP manually ───────────────────────────

@router.post("/ban-ip")
def ban_ip(
    request: Request,
    ip_address: str = Form(...),
    reason: str = Form(""),
    permanent: str = Form("false"),
    db: Session = Depends(get_db_dep),
):
    user = get_current_user_from_cookie(request, db)
    if not user or user.role not in [UserRole.SUPER_ADMIN, UserRole.ADMIN]:
        return RedirectResponse("/auth/login", status_code=303)
    from datetime import timedelta
    existing = db.query(BannedIP).filter_by(ip_address=ip_address).first()
    if not existing:
        ban = BannedIP(
            ip_address=ip_address,
            reason=reason or "Manual ban by admin",
            banned_by=user.id,
            is_permanent=(permanent == "true"),
            expires_at=None if permanent == "true" else
                       __import__("datetime").datetime.now(
                           __import__("datetime").timezone.utc) + timedelta(days=7),
        )
        db.add(ban)
        audit(db, "ip_banned", user_id=user.id,
              details=f"Manually banned IP: {ip_address}",
              ip=get_client_ip(request), status="success")
    return RedirectResponse("/auth/security", status_code=303)
