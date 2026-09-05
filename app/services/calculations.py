"""Deterministic project-control arithmetic.

Every function here is pure, zero-division safe and independently testable.
No route handler performs arithmetic of its own.
"""
from __future__ import annotations

from datetime import date, timedelta


def safe_div(numerator, denominator):
    """Return numerator/denominator, or None when the result is undefined."""
    try:
        if numerator is None or denominator is None:
            return None
        denominator = float(denominator)
        if denominator == 0.0:
            return None
        return float(numerator) / denominator
    except (TypeError, ValueError):
        return None


def pct(numerator, denominator, cap=None):
    """Percentage, or None when undefined. Optionally capped."""
    ratio = safe_div(numerator, denominator)
    if ratio is None:
        return None
    value = ratio * 100.0
    if cap is not None:
        value = min(value, cap)
    return value


def achievement_pct(actual, planned):
    """Daily achievement: actual / planned * 100."""
    return pct(actual, planned)


def quantity_per_worker_day(actual_quantity, workers):
    return safe_div(actual_quantity, workers)


def quantity_per_worker_hour(actual_quantity, workers, hours):
    if not workers or not hours:
        return None
    return safe_div(actual_quantity, float(workers) * float(hours))


def quantity_progress_pct(completed_quantity, total_required_quantity):
    """Quantity-based progress, capped at 100%."""
    return pct(completed_quantity, total_required_quantity, cap=100.0)


def weighted_progress(items):
    """Weighted rollup of (weight, percent_complete) pairs.

    Never a simple mean: items without a positive weight are ignored, and the
    result is bounded to 0..100. Returns None when no weighted item exists.
    """
    total_weight = 0.0
    accumulated = 0.0
    for weight, percent in items:
        try:
            w = float(weight or 0.0)
            p = float(percent or 0.0)
        except (TypeError, ValueError):
            continue
        if w <= 0:
            continue
        p = max(0.0, min(p, 100.0))
        total_weight += w
        accumulated += w * p
    if total_weight <= 0:
        return None
    return max(0.0, min(accumulated / total_weight, 100.0))


def elapsed_planned_pct(start, finish, as_of=None):
    """Time-elapsed planned percentage between two dates.

    Used only where an activity carries no explicit planned S-curve. Returns
    None when the dates are missing.
    """
    if not start or not finish:
        return None
    as_of = as_of or date.today()
    # Finish is tested first so a zero-duration milestone reads 100% planned on
    # its own date rather than 0%.
    if as_of >= finish:
        return 100.0
    if as_of <= start:
        return 0.0
    span = (finish - start).days
    if span <= 0:
        return 100.0
    return (as_of - start).days / span * 100.0


def variance_pp(actual_pct, planned_pct):
    """Variance in percentage points (negative means behind plan)."""
    if actual_pct is None or planned_pct is None:
        return None
    return float(actual_pct) - float(planned_pct)


def delay_days(baseline_date, comparison_date):
    """Positive when comparison_date is later than baseline_date."""
    if not baseline_date or not comparison_date:
        return None
    return (comparison_date - baseline_date).days


def production_rate(daily_quantities):
    """Mean production per active working day.

    Only days with a positive quantity count as active working days -- idle days
    must not deflate the rate into a meaningless number.
    """
    active = [q for q in daily_quantities if q and q > 0]
    if not active:
        return None, 0
    return sum(active) / len(active), len(active)


def forecast_remaining(total_required, completed, rate_per_day):
    """Remaining quantity and working days at the given rate."""
    if total_required is None:
        return None, None
    remaining = max(float(total_required) - float(completed or 0.0), 0.0)
    if not rate_per_day or rate_per_day <= 0:
        return remaining, None
    return remaining, remaining / rate_per_day


def forecast_finish_date(start_from, working_days_remaining, working_days_per_week=6):
    """Convert working days remaining into a calendar finish date.

    Deterministic: spreads the remaining working days over a week that contains
    `working_days_per_week` working days.
    """
    if working_days_remaining is None:
        return None
    start_from = start_from or date.today()
    if working_days_per_week <= 0:
        working_days_per_week = 6
    calendar_days = working_days_remaining * (7.0 / working_days_per_week)
    return start_from + timedelta(days=int(round(calendar_days)))


def utilisation_pct(working_hours, idle_hours, breakdown_hours):
    total = (working_hours or 0.0) + (idle_hours or 0.0) + (breakdown_hours or 0.0)
    return pct(working_hours or 0.0, total)


def available_stock(accepted_receipts, adjustments, issued_to_workfront):
    """available = accepted receipts + adjustments - issued to workfront."""
    return (accepted_receipts or 0.0) + (adjustments or 0.0) - (issued_to_workfront or 0.0)


def man_hours(workers, hours, overtime=0.0):
    return (workers or 0) * (hours or 0.0) + (overtime or 0.0)
