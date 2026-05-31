"""
Security Engine
===============
- Password hashing
- JWT token creation and verification
- User authentication
- IP banning
- Brute force protection
- Audit logging
"""
import os
from datetime import datetime, timezone, timedelta
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session
from billing_system.security.models import (
    User, UserRole, AuditLog, BannedIP, LoginAttempt
)

# ── Config ────────────────────────────────────
SECRET_KEY      = os.getenv("SECRET_KEY", "hotspotpro-super-secret-change-in-production-2024")
ALGORITHM       = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 8   # 8 hours
MAX_FAILED_ATTEMPTS = 5                # lock after 5 failed logins
BAN_THRESHOLD       = 10              # ban IP after 10 failed attempts in 1 hour

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ── Password ──────────────────────────────────

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)

def is_strong_password(password: str) -> tuple[bool, str]:
    if len(password) < 8:
        return False, "Password must be at least 8 characters"
    if not any(c.isupper() for c in password):
        return False, "Password must contain at least one uppercase letter"
    if not any(c.islower() for c in password):
        return False, "Password must contain at least one lowercase letter"
    if not any(c.isdigit() for c in password):
        return False, "Password must contain at least one number"
    if not any(c in "!@#$%^&*()_+-=[]{}|;':\",./<>?" for c in password):
        return False, "Password must contain at least one special character"
    return True, "OK"


# ── JWT Tokens ────────────────────────────────

def create_access_token(data: dict, expires_delta: timedelta = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire, "iat": datetime.now(timezone.utc)})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def verify_token(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None


# ── IP Security ───────────────────────────────

def is_ip_banned(db: Session, ip: str) -> bool:
    now = datetime.now(timezone.utc)
    ban = db.query(BannedIP).filter_by(ip_address=ip).first()
    if not ban:
        return False
    if ban.is_permanent:
        return True
    if ban.expires_at and ban.expires_at > now:
        return True
    if ban.expires_at and ban.expires_at <= now:
        db.delete(ban)
        db.flush()
        return False
    return False

def check_and_ban_ip(db: Session, ip: str) -> bool:
    from datetime import timedelta
    one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
    failed_count = (
        db.query(LoginAttempt)
        .filter(
            LoginAttempt.ip_address == ip,
            LoginAttempt.success == False,
            LoginAttempt.created_at >= one_hour_ago,
        )
        .count()
    )
    if failed_count >= BAN_THRESHOLD:
        existing = db.query(BannedIP).filter_by(ip_address=ip).first()
        if not existing:
            ban = BannedIP(
                ip_address=ip,
                reason=f"Automatic ban: {failed_count} failed login attempts in 1 hour",
                is_permanent=False,
                expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
            )
            db.add(ban)
            db.flush()
        return True
    return False

def record_login_attempt(db: Session, ip: str, username: str,
                         success: bool, user_agent: str = None):
    attempt = LoginAttempt(
        ip_address=ip,
        username=username,
        success=success,
        user_agent=user_agent,
    )
    db.add(attempt)
    db.flush()


# ── Audit Logging ─────────────────────────────

def audit(db: Session, action: str, user_id: str = None,
          resource: str = None, resource_id: str = None,
          details: str = None, ip: str = None,
          user_agent: str = None, status: str = "success"):
    log = AuditLog(
        user_id=user_id,
        action=action,
        resource=resource,
        resource_id=resource_id,
        details=details,
        ip_address=ip,
        user_agent=user_agent,
        status=status,
    )
    db.add(log)
    db.flush()


# ── User Auth ─────────────────────────────────

def authenticate_user(db: Session, username: str,
                      password: str, ip: str,
                      user_agent: str = None) -> tuple[Optional[User], str]:
    """
    Returns (user, error_message).
    If successful: (user, "")
    If failed: (None, reason)
    """
    user = db.query(User).filter(
        (User.username == username) | (User.email == username)
    ).first()

    if not user:
        record_login_attempt(db, ip, username, False, user_agent)
        audit(db, "login_failed", details=f"Unknown user: {username}",
              ip=ip, user_agent=user_agent, status="failed")
        return None, "Invalid username or password"

    if not user.is_active:
        audit(db, "login_blocked", user_id=user.id,
              details="Account inactive", ip=ip, status="blocked")
        return None, "Account is inactive"

    if user.is_locked:
        audit(db, "login_blocked", user_id=user.id,
              details="Account locked", ip=ip, status="blocked")
        return None, "Account is locked due to too many failed attempts. Contact admin."

    if not verify_password(password, user.hashed_password):
        user.failed_attempts += 1
        if user.failed_attempts >= MAX_FAILED_ATTEMPTS:
            user.is_locked = True
            audit(db, "account_locked", user_id=user.id,
                  details=f"Locked after {user.failed_attempts} failed attempts",
                  ip=ip, status="security")
        record_login_attempt(db, ip, username, False, user_agent)
        audit(db, "login_failed", user_id=user.id,
              details=f"Wrong password attempt {user.failed_attempts}",
              ip=ip, user_agent=user_agent, status="failed")
        db.flush()
        remaining = MAX_FAILED_ATTEMPTS - user.failed_attempts
        if remaining > 0:
            return None, f"Invalid password. {remaining} attempts remaining."
        return None, "Account locked. Contact admin."

    # Success
    user.failed_attempts = 0
    user.last_login = datetime.now(timezone.utc)
    user.last_ip = ip
    record_login_attempt(db, ip, username, True, user_agent)
    audit(db, "login_success", user_id=user.id,
          ip=ip, user_agent=user_agent, status="success")
    db.flush()
    return user, ""


# ── User Management ───────────────────────────

def create_user(db: Session, username: str, email: str,
                full_name: str, password: str,
                role: UserRole = UserRole.STAFF) -> tuple[Optional[User], str]:
    strong, msg = is_strong_password(password)
    if not strong:
        return None, msg

    existing = db.query(User).filter(
        (User.username == username) | (User.email == email)
    ).first()
    if existing:
        return None, "Username or email already exists"

    user = User(
        username=username,
        email=email,
        full_name=full_name,
        hashed_password=hash_password(password),
        role=role,
    )
    db.add(user)
    db.flush()
    return user, ""

def get_current_user(db: Session, token: str) -> Optional[User]:
    payload = verify_token(token)
    if not payload:
        return None
    user_id = payload.get("sub")
    if not user_id:
        return None
    user = db.query(User).filter_by(id=user_id).first()
    if not user or not user.is_active or user.is_locked:
        return None
    return user
