"""
Email Service
=============
Sends verification emails, welcome emails,
payment reminders using Gmail SMTP.
"""
import smtplib
import secrets
from datetime import datetime, timezone, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from sqlalchemy.orm import Session
from billing_system.security.isp_models import EmailVerification

# ── Config ────────────────────────────────────
GMAIL_USER     = "fredbackson3@gmail.com"
GMAIL_PASSWORD = "xnrx amvu xdkt hgwx"
BASE_URL       = "https://stunning-space-trout-wrq999xr9pvq29r5g-8000.app.github.dev"


# ── Send email ────────────────────────────────

def send_email(to: str, subject: str, html_body: str) -> bool:
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = f"HotspotPro <{GMAIL_USER}>"
        msg["To"]      = to
        msg.attach(MIMEText(html_body, "html"))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_USER, GMAIL_PASSWORD.replace(" ", ""))
            server.sendmail(GMAIL_USER, to, msg.as_string())
        return True
    except Exception as e:
        print(f"Email error: {e}")
        return False


# ── Verification token ────────────────────────

def create_verification_token(db: Session, user_id: str, email: str) -> str:
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(hours=24)
    verification = EmailVerification(
        user_id=user_id,
        token=token,
        email=email,
        expires_at=expires,
    )
    db.add(verification)
    db.flush()
    return token


def verify_email_token(db: Session, token: str):
    v = db.query(EmailVerification).filter_by(token=token, is_used=False).first()
    if not v:
        return None, "Invalid or expired verification link"
    if v.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        return None, "Verification link has expired. Please register again."
    v.is_used = True
    db.flush()
    return v, ""


# ── Email templates ───────────────────────────

def send_verification_email(to: str, company_name: str, token: str) -> bool:
    verify_url = f"{BASE_URL}/isp/verify-email/{token}"
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
      <style>
        body {{ font-family: Arial, sans-serif; background: #0f1117; color: #f0f2ff; margin: 0; padding: 20px; }}
        .container {{ max-width: 600px; margin: 0 auto; background: #1a1d27; border-radius: 16px; padding: 40px; }}
        .logo {{ font-size: 24px; font-weight: bold; color: #00e5a0; margin-bottom: 24px; }}
        .title {{ font-size: 22px; font-weight: bold; margin-bottom: 16px; }}
        .text {{ color: #9ca3af; line-height: 1.6; margin-bottom: 24px; }}
        .btn {{ display: inline-block; background: #00e5a0; color: #0f1117; padding: 14px 32px; border-radius: 8px; text-decoration: none; font-weight: bold; font-size: 16px; }}
        .footer {{ margin-top: 32px; color: #6b7280; font-size: 12px; border-top: 1px solid #2e3248; padding-top: 20px; }}
        .warning {{ background: #1e2235; border-left: 3px solid #00e5a0; padding: 12px 16px; border-radius: 4px; font-size: 13px; color: #9ca3af; margin-top: 24px; }}
      </style>
    </head>
    <body>
      <div class="container">
        <div class="logo">⚡ HotspotPro</div>
        <div class="title">Verify your email address</div>
        <div class="text">
          Hello {company_name},<br><br>
          Thank you for registering with HotspotPro — the professional WiFi hotspot billing platform.<br><br>
          Please verify your email address to activate your account and start managing your hotspot business.
        </div>
        <a href="{verify_url}" class="btn">✅ Verify Email Address</a>
        <div class="warning">
          ⏰ This link expires in 24 hours.<br>
          If you did not create this account, please ignore this email.
        </div>
        <div class="footer">
          HotspotPro — Professional WiFi Billing for ISPs<br>
          This is an automated email. Do not reply.
        </div>
      </div>
    </body>
    </html>
    """
    return send_email(to, "Verify your HotspotPro account", html)


def send_welcome_email(to: str, company_name: str, username: str) -> bool:
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
      <style>
        body {{ font-family: Arial, sans-serif; background: #0f1117; color: #f0f2ff; margin: 0; padding: 20px; }}
        .container {{ max-width: 600px; margin: 0 auto; background: #1a1d27; border-radius: 16px; padding: 40px; }}
        .logo {{ font-size: 24px; font-weight: bold; color: #00e5a0; margin-bottom: 24px; }}
        .title {{ font-size: 22px; font-weight: bold; margin-bottom: 16px; }}
        .text {{ color: #9ca3af; line-height: 1.6; margin-bottom: 24px; }}
        .btn {{ display: inline-block; background: #00e5a0; color: #0f1117; padding: 14px 32px; border-radius: 8px; text-decoration: none; font-weight: bold; font-size: 16px; }}
        .steps {{ background: #22263a; border-radius: 8px; padding: 20px; margin: 24px 0; }}
        .step {{ display: flex; gap: 12px; margin-bottom: 12px; color: #9ca3af; font-size: 14px; }}
        .step-num {{ background: #00e5a0; color: #0f1117; width: 24px; height: 24px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-weight: bold; font-size: 12px; flex-shrink: 0; }}
        .footer {{ margin-top: 32px; color: #6b7280; font-size: 12px; border-top: 1px solid #2e3248; padding-top: 20px; }}
      </style>
    </head>
    <body>
      <div class="container">
        <div class="logo">⚡ HotspotPro</div>
        <div class="title">Welcome to HotspotPro, {company_name}! 🎉</div>
        <div class="text">
          Your account is now active. Here is how to get started:
        </div>
        <div class="steps">
          <div class="step"><div class="step-num">1</div> Set up your company profile and helpline</div>
          <div class="step"><div class="step-num">2</div> Create your WiFi packages (up to 12)</div>
          <div class="step"><div class="step-num">3</div> Customize your dashboard theme</div>
          <div class="step"><div class="step-num">4</div> Add your first customer</div>
          <div class="step"><div class="step-num">5</div> Generate your first invoice</div>
        </div>
        <a href="{BASE_URL}/isp/dashboard" class="btn">🚀 Go to Dashboard</a>
        <div class="footer">
          Your username: <strong>{username}</strong><br>
          HotspotPro — Professional WiFi Billing for ISPs
        </div>
      </div>
    </body>
    </html>
    """
    return send_email(to, f"Welcome to HotspotPro — {company_name}", html)


def send_payment_reminder(to: str, company_name: str,
                          amount: float, due_date: str) -> bool:
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
      <style>
        body {{ font-family: Arial, sans-serif; background: #0f1117; color: #f0f2ff; margin: 0; padding: 20px; }}
        .container {{ max-width: 600px; margin: 0 auto; background: #1a1d27; border-radius: 16px; padding: 40px; }}
        .logo {{ font-size: 24px; font-weight: bold; color: #00e5a0; margin-bottom: 24px; }}
        .title {{ font-size: 22px; font-weight: bold; margin-bottom: 16px; color: #ffb547; }}
        .amount {{ font-size: 36px; font-weight: bold; color: #00e5a0; margin: 20px 0; }}
        .text {{ color: #9ca3af; line-height: 1.6; margin-bottom: 24px; }}
        .btn {{ display: inline-block; background: #00e5a0; color: #0f1117; padding: 14px 32px; border-radius: 8px; text-decoration: none; font-weight: bold; font-size: 16px; }}
        .footer {{ margin-top: 32px; color: #6b7280; font-size: 12px; border-top: 1px solid #2e3248; padding-top: 20px; }}
      </style>
    </head>
    <body>
      <div class="container">
        <div class="logo">⚡ HotspotPro</div>
        <div class="title">⚠️ Payment Reminder</div>
        <div class="text">Hello {company_name},</div>
        <div class="text">Your HotspotPro subscription payment is due on <strong>{due_date}</strong>.</div>
        <div class="amount">KES {amount:,.0f}</div>
        <div class="text">
          Please pay via M-Pesa Paybill to keep your account active.<br>
          Accounts unpaid after 3 days grace period will be suspended.
        </div>
        <a href="{BASE_URL}/isp/billing" class="btn">💳 Pay Now</a>
        <div class="footer">
          HotspotPro — Professional WiFi Billing for ISPs
        </div>
      </div>
    </body>
    </html>
    """
    return send_email(to, f"Payment Reminder — KES {amount:,.0f} due {due_date}", html)
