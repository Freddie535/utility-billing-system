"""
Security Models
===============
User, Role, AuditLog, BannedIP, LoginAttempt
"""
import uuid
from datetime import datetime, timezone
from enum import Enum as PyEnum
from sqlalchemy import (
    Column, String, Boolean, DateTime,
    ForeignKey, Enum, Text, Integer, Index
)
from sqlalchemy.orm import relationship
from billing_system.models.models import Base

def _uuid(): return str(uuid.uuid4())
def _now():  return datetime.now(timezone.utc)

class UserRole(PyEnum):
    SUPER_ADMIN = "super_admin"
    ADMIN       = "admin"
    STAFF       = "staff"
    ISP_OWNER   = "isp_owner"

class User(Base):
    __tablename__ = "users"
    id            = Column(String(36), primary_key=True, default=_uuid)
    email         = Column(String(255), unique=True, nullable=False, index=True)
    username      = Column(String(100), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    full_name     = Column(String(255), nullable=False)
    role          = Column(Enum(UserRole), nullable=False, default=UserRole.STAFF)
    is_active     = Column(Boolean, nullable=False, default=True)
    is_locked     = Column(Boolean, nullable=False, default=False)
    failed_attempts = Column(Integer, nullable=False, default=0)
    last_login    = Column(DateTime(timezone=True), nullable=True)
    last_ip       = Column(String(45), nullable=True)
    created_at    = Column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at    = Column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)
    audit_logs    = relationship("AuditLog", back_populates="user")
    def __repr__(self): return f"<User {self.username} ({self.role.value})>"

class AuditLog(Base):
    __tablename__ = "audit_logs"
    id         = Column(String(36), primary_key=True, default=_uuid)
    user_id    = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    action     = Column(String(100), nullable=False)
    resource   = Column(String(100), nullable=True)
    resource_id= Column(String(36), nullable=True)
    details    = Column(Text, nullable=True)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(255), nullable=True)
    status     = Column(String(20), nullable=False, default="success")
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    user       = relationship("User", back_populates="audit_logs")
    __table_args__ = (Index("ix_audit_created", "created_at"),)
    def __repr__(self): return f"<AuditLog {self.action} by {self.user_id}>"

class BannedIP(Base):
    __tablename__ = "banned_ips"
    id         = Column(String(36), primary_key=True, default=_uuid)
    ip_address = Column(String(45), unique=True, nullable=False, index=True)
    reason     = Column(String(255), nullable=True)
    banned_by  = Column(String(36), ForeignKey("users.id"), nullable=True)
    is_permanent = Column(Boolean, nullable=False, default=False)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    def __repr__(self): return f"<BannedIP {self.ip_address}>"

class LoginAttempt(Base):
    __tablename__ = "login_attempts"
    id         = Column(String(36), primary_key=True, default=_uuid)
    ip_address = Column(String(45), nullable=False, index=True)
    username   = Column(String(100), nullable=True)
    success    = Column(Boolean, nullable=False, default=False)
    user_agent = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    __table_args__ = (Index("ix_login_ip_created", "ip_address", "created_at"),)
    def __repr__(self): return f"<LoginAttempt {self.ip_address} {'OK' if self.success else 'FAIL'}>"
