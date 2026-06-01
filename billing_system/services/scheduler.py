"""
Automated Billing Scheduler
============================
Runs background jobs:
- Every day at midnight: generate invoices
- Every day at 9am: send payment reminders
- Every day at 10am: mark overdue invoices
- Every hour: check and suspend unpaid accounts
"""
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.orm import Session

from billing_system.db.database import SessionLocal
from billing_system.models.models import (
    Customer, Meter, Invoice, BillingCycle,
    InvoiceStatus, CustomerStatus, MeterStatus,
    Payment, PaymentStatus
)
from billing_system.services.billing_service import BillingService

scheduler = BackgroundScheduler(timezone="Africa/Nairobi")


# ── Helpers ───────────────────────────────────

def get_db() -> Session:
    return SessionLocal()


def log(msg: str):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[SCHEDULER {now}] {msg}")


# ── Job 1: Open billing cycles ────────────────

def open_monthly_cycles():
    """
    On the 1st of every month, open a new billing cycle
    for every active customer who doesn't have one yet.
    """
    db = get_db()
    try:
        now   = datetime.now(timezone.utc)
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        # Last day of month
        if now.month == 12:
            end = now.replace(year=now.year+1, month=1, day=1) - timedelta(seconds=1)
        else:
            end = now.replace(month=now.month+1, day=1) - timedelta(seconds=1)

        customers = db.query(Customer).filter_by(status=CustomerStatus.ACTIVE).all()
        opened = 0
        for customer in customers:
            existing = db.query(BillingCycle).filter(
                BillingCycle.customer_id == customer.id,
                BillingCycle.period_start == start,
            ).first()
            if not existing:
                BillingService.open_billing_cycle(
                    db,
                    customer_id=customer.id,
                    period_start=start,
                    period_end=end,
                )
                opened += 1

        db.commit()
        log(f"Opened {opened} new billing cycles for {now.strftime('%B %Y')}")
    except Exception as e:
        log(f"ERROR opening cycles: {e}")
        db.rollback()
    finally:
        db.close()


# ── Job 2: Record meter readings ──────────────

def record_automated_readings():
    """
    Every day, record a reading of 1 session for each
    active meter. Links to the current open billing cycle.
    """
    db = get_db()
    try:
        now   = datetime.now(timezone.utc)
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        meters = db.query(Meter).filter_by(status=MeterStatus.ACTIVE).all()
        recorded = 0

        for meter in meters:
            cycle = db.query(BillingCycle).filter(
                BillingCycle.customer_id == meter.customer_id,
                BillingCycle.period_start == start,
                BillingCycle.is_closed == False,
            ).first()
            if not cycle:
                continue
            try:
                prev = meter.last_read_value or Decimal("0")
                rec = BillingService.record_reading(
                    db,
                    meter_id=meter.id,
                    reading_value=prev + Decimal("1"),
                    source="auto",
                    notes=f"Auto-recorded on {now.strftime('%d %b %Y')}",
                )
                rec.billing_cycle_id = cycle.id
                recorded += 1
            except Exception as e:
                log(f"Error recording meter {meter.serial_number}: {e}")

        db.commit()
        log(f"Auto-recorded {recorded} meter readings")
    except Exception as e:
        log(f"ERROR recording readings: {e}")
        db.rollback()
    finally:
        db.close()


# ── Job 3: Generate monthly invoices ──────────

def generate_monthly_invoices():
    """
    On the last day of the month, close billing cycles
    and generate invoices for all active customers.
    """
    db = get_db()
    try:
        now   = datetime.now(timezone.utc)
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        # Find all open cycles for this month
        cycles = db.query(BillingCycle).filter(
            BillingCycle.period_start == start,
            BillingCycle.is_closed == False,
        ).all()

        generated = 0
        for cycle in cycles:
            try:
                # Close the cycle
                BillingService.close_billing_cycle(db, cycle.id)

                # Check if invoice already exists
                existing_inv = db.query(Invoice).filter_by(
                    billing_cycle_id=cycle.id).first()
                if existing_inv:
                    continue

                # Generate invoice
                invoice = BillingService.generate_invoice(
                    db,
                    billing_cycle_id=cycle.id,
                    tax_rate=Decimal("0.16"),
                    due_days=14,
                )
                # Issue it
                BillingService.issue_invoice(db, invoice.id)
                generated += 1

                # Send email notification
                customer = db.query(Customer).filter_by(
                    id=cycle.customer_id).first()
                if customer and customer.email:
                    try:
                        from billing_system.security.email_service import send_email
                        send_email(
                            customer.email,
                            f"Your invoice is ready — KES {invoice.total_due:.2f}",
                            f"""
                            <div style="font-family:Arial;background:#0f1117;color:#f0f2ff;padding:20px;">
                            <h2 style="color:#00e5a0;">⚡ HotspotPro</h2>
                            <p>Your invoice for {now.strftime('%B %Y')} is ready.</p>
                            <h3 style="color:#00e5a0;">Total Due: KES {invoice.total_due:.2f}</h3>
                            <p>Due date: {invoice.due_date.strftime('%d %b %Y')}</p>
                            <p>Please pay via M-Pesa to keep your service active.</p>
                            </div>
                            """
                        )
                    except Exception as email_err:
                        log(f"Email error for {customer.email}: {email_err}")

            except Exception as e:
                log(f"Error generating invoice for cycle {cycle.id}: {e}")

        db.commit()
        log(f"Generated {generated} invoices for {now.strftime('%B %Y')}")
    except Exception as e:
        log(f"ERROR generating invoices: {e}")
        db.rollback()
    finally:
        db.close()


# ── Job 4: Send payment reminders ─────────────

def send_payment_reminders():
    """
    Every day at 9am, send reminders for invoices
    due in 7 days and 3 days.
    """
    db = get_db()
    try:
        now      = datetime.now(timezone.utc)
        in_7days = now + timedelta(days=7)
        in_3days = now + timedelta(days=3)
        sent = 0

        invoices = db.query(Invoice).filter(
            Invoice.status == InvoiceStatus.ISSUED,
            Invoice.due_date <= in_7days,
            Invoice.due_date >= now,
        ).all()

        for invoice in invoices:
            customer = db.query(Customer).filter_by(
                id=invoice.customer_id).first()
            if not customer or not customer.email:
                continue
            days_left = (invoice.due_date - now).days
            if days_left in [7, 3, 1]:
                try:
                    from billing_system.security.email_service import send_email
                    send_email(
                        customer.email,
                        f"⚠️ Payment reminder — KES {invoice.total_due:.2f} due in {days_left} day(s)",
                        f"""
                        <div style="font-family:Arial;background:#0f1117;color:#f0f2ff;padding:20px;">
                        <h2 style="color:#00e5a0;">⚡ HotspotPro</h2>
                        <h3 style="color:#ffb547;">⚠️ Payment Reminder</h3>
                        <p>Invoice <strong>{invoice.invoice_number}</strong> is due in
                        <strong style="color:#ff4d6d;">{days_left} day(s)</strong>.</p>
                        <h3 style="color:#00e5a0;">Amount Due: KES {invoice.total_due:.2f}</h3>
                        <p>Due date: {invoice.due_date.strftime('%d %b %Y')}</p>
                        <p>Pay now to avoid service suspension.</p>
                        </div>
                        """
                    )
                    sent += 1
                except Exception as e:
                    log(f"Reminder email error: {e}")

        db.commit()
        log(f"Sent {sent} payment reminders")
    except Exception as e:
        log(f"ERROR sending reminders: {e}")
        db.rollback()
    finally:
        db.close()


# ── Job 5: Mark overdue invoices ──────────────

def mark_overdue_invoices():
    """
    Every day at 10am, mark past-due invoices as OVERDUE.
    """
    db = get_db()
    try:
        now = datetime.now(timezone.utc)
        invoices = db.query(Invoice).filter(
            Invoice.status == InvoiceStatus.ISSUED,
            Invoice.due_date < now,
        ).all()

        marked = 0
        for invoice in invoices:
            invoice.status = InvoiceStatus.OVERDUE
            marked += 1

        db.commit()
        log(f"Marked {marked} invoices as overdue")
    except Exception as e:
        log(f"ERROR marking overdue: {e}")
        db.rollback()
    finally:
        db.close()


# ── Job 6: Suspend unpaid customers ───────────

def suspend_unpaid_customers():
    """
    Every hour, suspend customers with invoices
    overdue by more than 3 days.
    """
    db = get_db()
    try:
        now          = datetime.now(timezone.utc)
        grace_period = now - timedelta(days=3)

        overdue_invoices = db.query(Invoice).filter(
            Invoice.status == InvoiceStatus.OVERDUE,
            Invoice.due_date < grace_period,
        ).all()

        suspended = 0
        for invoice in overdue_invoices:
            customer = db.query(Customer).filter_by(
                id=invoice.customer_id).first()
            if customer and customer.status == CustomerStatus.ACTIVE:
                customer.status = CustomerStatus.SUSPENDED

                # Deactivate their meters
                meters = db.query(Meter).filter_by(
                    customer_id=customer.id).all()
                for meter in meters:
                    meter.status = MeterStatus.INACTIVE

                suspended += 1

                # Send suspension email
                if customer.email:
                    try:
                        from billing_system.security.email_service import send_email
                        send_email(
                            customer.email,
                            "⛔ Your account has been suspended",
                            f"""
                            <div style="font-family:Arial;background:#0f1117;color:#f0f2ff;padding:20px;">
                            <h2 style="color:#00e5a0;">⚡ HotspotPro</h2>
                            <h3 style="color:#ff4d6d;">⛔ Account Suspended</h3>
                            <p>Your account has been suspended due to non-payment.</p>
                            <p>Invoice <strong>{invoice.invoice_number}</strong> —
                            KES {invoice.total_due:.2f} is overdue.</p>
                            <p>Please pay immediately to restore your service.</p>
                            </div>
                            """
                        )
                    except Exception as e:
                        log(f"Suspension email error: {e}")

        db.commit()
        log(f"Suspended {suspended} customers for non-payment")
    except Exception as e:
        log(f"ERROR suspending customers: {e}")
        db.rollback()
    finally:
        db.close()


# ── Job 7: Reactivate paid customers ──────────

def reactivate_paid_customers():
    """
    Every hour, reactivate suspended customers
    who have paid their overdue invoices.
    """
    db = get_db()
    try:
        suspended = db.query(Customer).filter_by(
            status=CustomerStatus.SUSPENDED).all()

        reactivated = 0
        for customer in suspended:
            unpaid = db.query(Invoice).filter(
                Invoice.customer_id == customer.id,
                Invoice.status.in_([InvoiceStatus.OVERDUE, InvoiceStatus.ISSUED]),
            ).count()

            if unpaid == 0:
                customer.status = CustomerStatus.ACTIVE
                meters = db.query(Meter).filter_by(
                    customer_id=customer.id).all()
                for meter in meters:
                    meter.status = MeterStatus.ACTIVE
                reactivated += 1

                if customer.email:
                    try:
                        from billing_system.security.email_service import send_email
                        send_email(
                            customer.email,
                            "✅ Your account has been reactivated",
                            f"""
                            <div style="font-family:Arial;background:#0f1117;color:#f0f2ff;padding:20px;">
                            <h2 style="color:#00e5a0;">⚡ HotspotPro</h2>
                            <h3 style="color:#00e5a0;">✅ Account Reactivated</h3>
                            <p>Your payment has been confirmed and your account is now active.</p>
                            <p>Thank you for your payment!</p>
                            </div>
                            """
                        )
                    except Exception as e:
                        log(f"Reactivation email error: {e}")

        db.commit()
        log(f"Reactivated {reactivated} customers")
    except Exception as e:
        log(f"ERROR reactivating customers: {e}")
        db.rollback()
    finally:
        db.close()


# ── Start Scheduler ───────────────────────────

def start_scheduler():
    """Start all scheduled jobs."""

    # Open billing cycles — 1st of every month at 00:01
    scheduler.add_job(
        open_monthly_cycles,
        CronTrigger(day=1, hour=0, minute=1),
        id="open_cycles",
        replace_existing=True,
    )

    # Record daily readings — every day at 23:00
    scheduler.add_job(
        record_automated_readings,
        CronTrigger(hour=23, minute=0),
        id="record_readings",
        replace_existing=True,
    )

    # Generate invoices — last day of month at 23:30
    scheduler.add_job(
        generate_monthly_invoices,
        CronTrigger(day="last", hour=23, minute=30),
        id="generate_invoices",
        replace_existing=True,
    )

    # Payment reminders — every day at 9am
    scheduler.add_job(
        send_payment_reminders,
        CronTrigger(hour=9, minute=0),
        id="payment_reminders",
        replace_existing=True,
    )

    # Mark overdue — every day at 10am
    scheduler.add_job(
        mark_overdue_invoices,
        CronTrigger(hour=10, minute=0),
        id="mark_overdue",
        replace_existing=True,
    )

    # Suspend unpaid — every hour
    scheduler.add_job(
        suspend_unpaid_customers,
        CronTrigger(minute=0),
        id="suspend_unpaid",
        replace_existing=True,
    )

    # Reactivate paid — every hour at :30
    scheduler.add_job(
        reactivate_paid_customers,
        CronTrigger(minute=30),
        id="reactivate_paid",
        replace_existing=True,
    )

    scheduler.start()
    log("Scheduler started — 7 automated jobs running")
    log("Jobs: open_cycles, record_readings, generate_invoices,")
    log("      payment_reminders, mark_overdue, suspend_unpaid, reactivate_paid")
