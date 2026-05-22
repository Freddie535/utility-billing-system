import pytest
from decimal import Decimal
from datetime import datetime, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from billing_system.models.models import Base, TariffType, PaymentMethod
from billing_system.services.billing_service import BillingService, calculate_charge

@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

def make_flat_plan(db):
    return BillingService.create_tariff_plan(
        db,
        name="Test Flat",
        tariff_type=TariffType.FLAT,
        tiers=[{"tier_order": 1, "units_from": 0, "units_to": None, "rate": "50"}],
    )

def test_flat_charge(db):
    plan = make_flat_plan(db)
    charge, breakdown = calculate_charge(Decimal("1"), plan)
    assert charge == Decimal("50.0000")
    assert len(breakdown) == 1

def test_create_customer(db):
    c = BillingService.create_customer(
        db, account_number="TST-001", full_name="Test User")
    assert c.id is not None
    assert c.credit_balance == Decimal("0")

def test_install_meter(db):
    plan = make_flat_plan(db)
    c = BillingService.create_customer(
        db, account_number="TST-002", full_name="Meter User")
    m = BillingService.install_meter(
        db, customer_id=c.id, serial_number="S-001",
        tariff_plan_id=plan.id, initial_reading=Decimal("0"))
    assert m.last_read_value == Decimal("0")

def test_record_reading(db):
    plan = make_flat_plan(db)
    c = BillingService.create_customer(
        db, account_number="TST-003", full_name="Usage User")
    m = BillingService.install_meter(
        db, customer_id=c.id, serial_number="S-002",
        tariff_plan_id=plan.id, initial_reading=Decimal("0"))
    rec = BillingService.record_reading(
        db, meter_id=m.id, reading_value=Decimal("1"))
    assert rec.consumption == Decimal("1.000000")

def test_reading_below_previous_raises(db):
    plan = make_flat_plan(db)
    c = BillingService.create_customer(
        db, account_number="TST-004", full_name="Error User")
    m = BillingService.install_meter(
        db, customer_id=c.id, serial_number="S-003",
        tariff_plan_id=plan.id, initial_reading=Decimal("5"))
    with pytest.raises(ValueError):
        BillingService.record_reading(
            db, meter_id=m.id, reading_value=Decimal("3"))

def _full_cycle(db):
    plan = make_flat_plan(db)
    c = BillingService.create_customer(
        db, account_number="INV-001", full_name="Invoice User")
    m = BillingService.install_meter(
        db, customer_id=c.id, serial_number="S-INV-01",
        tariff_plan_id=plan.id, initial_reading=Decimal("0"))
    cycle = BillingService.open_billing_cycle(
        db, customer_id=c.id,
        period_start=datetime(2025, 6, 1, tzinfo=timezone.utc),
        period_end=datetime(2025, 6, 30, tzinfo=timezone.utc))
    rec = BillingService.record_reading(
        db, meter_id=m.id, reading_value=Decimal("1"))
    rec.billing_cycle_id = cycle.id
    db.flush()
    BillingService.close_billing_cycle(db, cycle.id)
    invoice = BillingService.generate_invoice(
        db, billing_cycle_id=cycle.id, tax_rate=Decimal("0.16"))
    return invoice, c

def test_invoice_total_is_positive(db):
    invoice, _ = _full_cycle(db)
    assert invoice.total_due > 0

def test_invoice_tax_computed(db):
    invoice, _ = _full_cycle(db)
    expected = (invoice.subtotal * Decimal("0.16")).quantize(Decimal("0.0001"))
    assert invoice.tax_amount == expected

def test_invoice_paid_on_full_payment(db):
    invoice, _ = _full_cycle(db)
    BillingService.issue_invoice(db, invoice.id)
    BillingService.record_payment(
        db, invoice_id=invoice.id,
        amount=invoice.total_due, method=PaymentMethod.MPESA)
    from billing_system.models.models import InvoiceStatus
    assert invoice.status == InvoiceStatus.PAID

def test_overpayment_credited(db):
    invoice, customer = _full_cycle(db)
    BillingService.issue_invoice(db, invoice.id)
    BillingService.record_payment(
        db, invoice_id=invoice.id,
        amount=invoice.total_due + Decimal("100"),
        method=PaymentMethod.CASH)
    assert customer.credit_balance == Decimal("100")
