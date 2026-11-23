"""Late fee calculation for overdue Meridian invoices."""

import math

GRACE_DAYS = 5
MONTHLY_RATE = 0.02
CAP_RATIO = 0.25


def compute_late_fee(amount_minor: int, days_overdue: int, *, enterprise: bool = False) -> int:
    """Late fee in minor units: 2% per started month after the grace period, capped at 25% of the amount."""
    if enterprise or days_overdue <= GRACE_DAYS:
        return 0
    months = math.ceil((days_overdue - GRACE_DAYS) / 30)
    fee = round(amount_minor * MONTHLY_RATE * months)
    return min(fee, int(amount_minor * CAP_RATIO))
