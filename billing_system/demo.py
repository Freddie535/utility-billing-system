from decimal import Decimal
from datetime import datetime, timezone
from billing_system.db.database import init_db, get_db
from billing_system.models.models import TariffType, PaymentMethod
from billing_system.services.billing_service import BillingService

def run():
    init_db()
    with get_db() as db:

        print("\n── Creating WiFi packages ──")
        packages = [
            {"name": "2hrs - KES 10",          "hours": 2,   "price": "10"},
            {"name": "3hrs - KES 15",          "hours": 3,   "price": "15"},
            {"name": "3hrs Streaming - KES 20","hours": 3,   "price": "20"},
            {"name": "12hrs - KES 20",         "hours": 12,  "price": "20"},
            {"name": "1 Day - KES 50",         "hours": 24,  "price": "50"},
            {"name": "3 Days - KES 150",       "hours": 72,  "price": "150"},
            {"name": "2 Weeks - KES 350",      "hours": 336, "price": "350"},
            {"name": "1 Month - KES 600",      "hours": 720, "price": "600"},
        ]
        plans = []
        for pkg in packages:
            plan = BillingService.create_tariff_plan(
                db,
                name=pkg["name"],
                tariff_type=TariffType.FLAT,
                currency="KES",
                standing_charge=Decimal("0"),
                description=f"{pkg['hours']} hour(s) WiFi access",
                tiers=[{
                    "tier_order": 1,
                    "units_from": 0,
                    "units_to": None,
                    "rate": pkg["price"],
                    "description": pkg["name"],
                }],
            )
            plans.append(plan)
            print(f"  + {plan.name}")

        print("\n── Creating customer ──")
        customer = BillingService.create_customer(
            db,
            account_number="ACC-00001",
            full_name="John Kamau",
            email="john.kamau@example.co.ke",
            phone="+254712345678",
            address="Nairobi, Kenya",
        )
        print(f"  + {customer}")

        print("\n── Installing meter (linked to 1 Day - KES 50 plan) ──")
        day_plan = plans[4]
        meter = BillingService.install_meter(
            db,
            customer_id=customer.id,
            serial_number="WIFI-00001",
            tariff_plan_id=day_plan.id,
            unit="session",
            initial_reading=Decimal("0"),
        )
        print(f"  + {meter}")

        print("\n── Opening billing cycle (June 2025) ──")
        cycle = BillingService.open_billing_cycle(
            db,
            customer_id=customer.id,
            period_start=datetime(2025, 6, 1, tzinfo=timezone.utc),
            period_end=datetime(2025, 6, 30, 23, 59, 59, tzinfo=timezone.utc),
        )
        print(f"  + {cycle}")

        print("\n── Recording session usage ──")
        rec = BillingService.record_reading(
            db,
            meter_id=meter.id,
            reading_value=Decimal("1"),
            source="hotspot",
            notes="1 day session purchased",
        )
        rec.billing_cycle_id = cycle.id
        db.flush()
        print(f"  + Session recorded: {rec.consumption} session(s)")

        print("\n── Closing billing cycle ──")
        BillingService.close_billing_cycle(db, cycle.id)
        print("  + Cycle closed")

        print("\n── Generating invoice ──")
        invoice = BillingService.generate_invoice(
            db,
            billing_cycle_id=cycle.id,
            tax_rate=Decimal("0.16"),
            due_days=7,
        )

        print(f"\n  Invoice: {invoice.invoice_number}")
        print(f"  {'─' * 55}")
        for li in invoice.line_items:
            print(f"  {li.description:<40} KES {li.amount:>8.2f}")
        print(f"  {'─' * 55}")
        print(f"  {'Subtotal':>40} KES {invoice.subtotal:>8.2f}")
        print(f"  {'VAT (16%)':>40} KES {invoice.tax_amount:>8.2f}")
        print(f"  {'TOTAL DUE':>40} KES {invoice.total_due:>8.2f}")

        print("\n── Issuing invoice ──")
        BillingService.issue_invoice(db, invoice.id)
        print(f"  + Status: {invoice.status.value}")

        print("\n── Recording M-Pesa payment ──")
        payment = BillingService.record_payment(
            db,
            invoice_id=invoice.id,
            amount=invoice.total_due,
            method=PaymentMethod.MPESA,
            reference="QHG7X4K21P",
        )
        print(f"  + Payment ref: {payment.reference}")
        print(f"  + Invoice status: {invoice.status.value}")

    print("\n✅  Demo complete!\n")

if __name__ == "__main__":
    run()
