from __future__ import annotations
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import List
from sqlalchemy.orm import Session
from billing_system.models.models import (
    Customer, Meter, TariffPlan, TariffTier, TariffType,
    UsageRecord, BillingCycle, Invoice, InvoiceLineItem, Payment,
    InvoiceStatus, PaymentStatus, CustomerStatus, MeterStatus,
)

def calculate_charge(consumption: Decimal, plan: TariffPlan):
    tiers: List[TariffTier] = sorted(plan.tiers, key=lambda t: t.tier_order)
    if not tiers:
        raise ValueError(f"TariffPlan {plan.id} has no tiers defined.")
    total = Decimal("0.0000")
    breakdown = []
    remaining = consumption

    if plan.tariff_type == TariffType.FLAT:
        rate = tiers[0].rate
        charge = (remaining * rate).quantize(Decimal("0.0001"), ROUND_HALF_UP)
        total = charge
        breakdown.append({
            "description": "Session charge",
            "units_from": Decimal("0"),
            "units_to": consumption,
            "quantity": consumption,
            "rate": rate,
            "amount": charge,
        })

    elif plan.tariff_type == TariffType.TIERED:
        consumed_so_far = Decimal("0")
        for tier in tiers:
            if remaining <= 0:
                break
            tier_size = ((tier.units_to - tier.units_from)
                         if tier.units_to is not None else remaining)
            slice_qty = min(remaining, tier_size)
            charge = (slice_qty * tier.rate).quantize(Decimal("0.0001"), ROUND_HALF_UP)
            total += charge
            breakdown.append({
                "description": tier.description or f"Tier {tier.tier_order}",
                "units_from": consumed_so_far,
                "units_to": consumed_so_far + slice_qty,
                "quantity": slice_qty,
                "rate": tier.rate,
                "amount": charge,
            })
            consumed_so_far += slice_qty
            remaining -= slice_qty

    elif plan.tariff_type == TariffType.BLOCK:
        matched_tier = tiers[-1]
        for tier in tiers:
            upper = tier.units_to if tier.units_to is not None else Decimal("Infinity")
            if tier.units_from <= consumption <= upper:
                matched_tier = tier
                break
        charge = (consumption * matched_tier.rate).quantize(Decimal("0.0001"), ROUND_HALF_UP)
        total = charge
        breakdown.append({
            "description": matched_tier.description or f"Block {matched_tier.tier_order}",
            "units_from": matched_tier.units_from,
            "units_to": matched_tier.units_to,
            "quantity": consumption,
            "rate": matched_tier.rate,
            "amount": charge,
        })

    return total, breakdown


def _next_invoice_number(db: Session) -> str:
    now = datetime.now(timezone.utc)
    prefix = f"INV-{now.strftime('%Y%m')}-"
    count = db.query(Invoice).filter(Invoice.invoice_number.like(f"{prefix}%")).count()
    return f"{prefix}{count + 1:06d}"


class BillingService:

    @staticmethod
    def create_customer(db, *, full_name, account_number, email=None, phone=None, address=None):
        c = Customer(
            full_name=full_name,
            account_number=account_number,
            email=email,
            phone=phone,
            address=address,
        )
        db.add(c)
        db.flush()
        return c

    @staticmethod
    def install_meter(db, *, customer_id, serial_number, tariff_plan_id,
                      unit="session", multiplier=Decimal("1.0"),
                      initial_reading=Decimal("0"), installed_at=None):
        now = installed_at or datetime.now(timezone.utc)
        m = Meter(
            customer_id=customer_id,
            serial_number=serial_number,
            tariff_plan_id=tariff_plan_id,
            unit=unit,
            multiplier=multiplier,
            installed_at=now,
            last_read_at=now,
            last_read_value=initial_reading,
        )
        db.add(m)
        db.flush()
        return m

    @staticmethod
    def create_tariff_plan(db, *, name, tariff_type, currency="KES",
                           standing_charge=Decimal("0"), tiers, description=None):
        plan = TariffPlan(
            name=name,
            description=description,
            tariff_type=tariff_type,
            currency=currency,
            standing_charge=Decimal(str(standing_charge)),
        )
        db.add(plan)
        db.flush()
        for t in tiers:
            db.add(TariffTier(
                plan_id=plan.id,
                tier_order=t["tier_order"],
                units_from=Decimal(str(t["units_from"])),
                units_to=Decimal(str(t["units_to"])) if t.get("units_to") is not None else None,
                rate=Decimal(str(t["rate"])),
                description=t.get("description"),
            ))
        db.flush()
        return plan

    @staticmethod
    def record_reading(db, *, meter_id, reading_value, read_at=None,
                       source="manual", notes=None, is_estimated=False):
        meter = db.query(Meter).filter_by(id=meter_id).one()
        if meter.status != MeterStatus.ACTIVE:
            raise ValueError(f"Meter {meter.serial_number} is not active.")
        previous = meter.last_read_value or Decimal("0")
        if reading_value < previous:
            raise ValueError(
                f"Reading {reading_value} is less than last reading {previous}."
            )
        consumption = ((reading_value - previous) * meter.multiplier).quantize(
            Decimal("0.000001"), ROUND_HALF_UP)
        now = read_at or datetime.now(timezone.utc)
        rec = UsageRecord(
            meter_id=meter_id,
            reading_value=reading_value,
            previous_value=previous,
            consumption=consumption,
            read_at=now,
            source=source,
            notes=notes,
            is_estimated=is_estimated,
        )
        db.add(rec)
        meter.last_read_value = reading_value
        meter.last_read_at = now
        db.flush()
        return rec

    @staticmethod
    def open_billing_cycle(db, *, customer_id, period_start, period_end):
        cycle = BillingCycle(
            customer_id=customer_id,
            period_start=period_start,
            period_end=period_end,
        )
        db.add(cycle)
        db.flush()
        return cycle

    @staticmethod
    def close_billing_cycle(db, cycle_id):
        cycle = db.query(BillingCycle).filter_by(id=cycle_id).one()
        if cycle.is_closed:
            raise ValueError("Billing cycle is already closed.")
        cycle.is_closed = True
        cycle.closed_at = datetime.now(timezone.utc)
        db.flush()
        return cycle

    @staticmethod
    def generate_invoice(db, *, billing_cycle_id, tax_rate=Decimal("0.16"),
                         due_days=30, apply_credit=True):
        cycle = db.query(BillingCycle).filter_by(id=billing_cycle_id).one()
        customer = cycle.customer
        if customer.status == CustomerStatus.CLOSED:
            raise ValueError("Cannot invoice a closed customer account.")

        usage_records = db.query(UsageRecord).filter_by(billing_cycle_id=billing_cycle_id).all()
        meter_consumption = {}
        for rec in usage_records:
            meter_consumption[rec.meter_id] = (
                meter_consumption.get(rec.meter_id, Decimal("0")) + rec.consumption)

        invoice = Invoice(
            invoice_number=_next_invoice_number(db),
            customer_id=customer.id,
            billing_cycle_id=billing_cycle_id,
            currency="KES",
            due_date=datetime.now(timezone.utc) + timedelta(days=due_days),
        )
        db.add(invoice)
        db.flush()

        subtotal = Decimal("0.0000")
        sort_order = 0

        for meter_id, consumption in meter_consumption.items():
            meter = db.query(Meter).filter_by(id=meter_id).one()
            plan = meter.tariff_plan
            if plan.standing_charge > 0:
                db.add(InvoiceLineItem(
                    invoice_id=invoice.id,
                    meter_id=meter_id,
                    description=f"Standing charge - {meter.serial_number}",
                    quantity=Decimal("1"),
                    unit="month",
                    unit_rate=plan.standing_charge,
                    amount=plan.standing_charge,
                    sort_order=sort_order,
                ))
                subtotal += plan.standing_charge
                sort_order += 1

            total_charge, breakdown = calculate_charge(consumption, plan)
            for s in breakdown:
                db.add(InvoiceLineItem(
                    invoice_id=invoice.id,
                    meter_id=meter_id,
                    description=f"{s['description']} - {meter.serial_number}",
                    quantity=s["quantity"],
                    unit=meter.unit,
                    unit_rate=s["rate"],
                    amount=s["amount"],
                    sort_order=sort_order,
                ))
                sort_order += 1
            subtotal += total_charge

        tax_amount = (subtotal * tax_rate).quantize(Decimal("0.0001"), ROUND_HALF_UP)
        credit_applied = Decimal("0.0000")
        if apply_credit and customer.credit_balance > 0:
            credit_applied = min(customer.credit_balance, subtotal + tax_amount)
            customer.credit_balance -= credit_applied

        invoice.subtotal = subtotal
        invoice.tax_amount = tax_amount
        invoice.credit_applied = credit_applied
        invoice.total_due = max(
            (subtotal + tax_amount - credit_applied).quantize(Decimal("0.0001"), ROUND_HALF_UP),
            Decimal("0"),
        )
        db.flush()
        return invoice

    @staticmethod
    def issue_invoice(db, invoice_id):
        invoice = db.query(Invoice).filter_by(id=invoice_id).one()
        if invoice.status != InvoiceStatus.DRAFT:
            raise ValueError("Only DRAFT invoices can be issued.")
        invoice.status = InvoiceStatus.ISSUED
        invoice.issued_at = datetime.now(timezone.utc)
        db.flush()
        return invoice

    @staticmethod
    def record_payment(db, *, invoice_id, amount, method, reference=None, paid_at=None):
        invoice = db.query(Invoice).filter_by(id=invoice_id).one()
        if invoice.status == InvoiceStatus.VOID:
            raise ValueError("Cannot pay a voided invoice.")
        prior = db.query(Payment).filter_by(
            invoice_id=invoice_id, status=PaymentStatus.CONFIRMED).all()
        total_paid = sum(p.amount for p in prior) + Decimal(str(amount))
        payment = Payment(
            invoice_id=invoice_id,
            customer_id=invoice.customer_id,
            amount=Decimal(str(amount)),
            currency=invoice.currency,
            method=method,
            reference=reference,
            status=PaymentStatus.CONFIRMED,
            paid_at=paid_at or datetime.now(timezone.utc),
        )
        db.add(payment)
        customer = db.query(Customer).filter_by(id=invoice.customer_id).one()
        if total_paid >= invoice.total_due:
            invoice.status = InvoiceStatus.PAID
            invoice.paid_at = payment.paid_at
            overpay = total_paid - invoice.total_due
            if overpay > 0:
                customer.credit_balance += overpay
        db.flush()
        return payment

    @staticmethod
    def void_invoice(db, invoice_id, reason=None):
        invoice = db.query(Invoice).filter_by(id=invoice_id).one()
        if invoice.status == InvoiceStatus.PAID:
            raise ValueError("Cannot void a paid invoice.")
        invoice.status = InvoiceStatus.VOID
        if reason:
            invoice.notes = (invoice.notes or "") + f"\nVoided: {reason}"
        db.flush()
        return invoice
