"""Project settings: configurable thresholds used by the control rules."""
from __future__ import annotations

from app.extensions import db
from app.models import ProjectSetting

#: key -> (default, type, category, description)
DEFAULT_SETTINGS = {
    "variance_at_risk_pp": (
        -5.0, "float", "Schedule",
        "Variance (percentage points, actual minus planned) at or above which an "
        "activity is ON TRACK. Below this it becomes AT RISK.",
    ),
    "variance_critical_pp": (
        -10.0, "float", "Schedule",
        "Variance (percentage points) below which an activity is CRITICAL.",
    ),
    "lookahead_short_weeks": (2, "int", "Schedule", "Short lookahead window in weeks."),
    "lookahead_long_weeks": (4, "int", "Schedule", "Long lookahead window in weeks."),
    "imminent_window_days": (
        7, "int", "Schedule",
        "Window in days used for 'starting soon' and 'finishing soon' lists.",
    ),
    "procurement_at_risk_days": (
        14, "int", "Procurement",
        "Days before required/planned delivery at which an undelivered package "
        "becomes AT RISK.",
    ),
    "stock_low_pct": (
        20.0, "float", "Materials",
        "Available stock below this percentage of remaining requirement is LOW STOCK.",
    ),
    "forecast_window_short_days": (
        7, "int", "Forecasting",
        "Short production-rate averaging window in calendar days.",
    ),
    "forecast_window_long_days": (
        14, "int", "Forecasting",
        "Long production-rate averaging window in calendar days.",
    ),
    "forecast_min_working_days": (
        3, "int", "Forecasting",
        "Minimum number of active working days required before a forecast is shown.",
    ),
    "progress_weight_basis": (
        "DURATION DERIVED", "str", "Progress",
        "Weighting basis for project rollup: APPROVED WEIGHT, DURATION DERIVED or QUANTITY.",
    ),
    "governing_schedule": (
        "CURRENT WORKING", "str", "Schedule",
        "Schedule version type that governs operational planning "
        "(CONTRACTUAL BASELINE is always retained for contractual comparison).",
    ),
    "report_number_prefix": (
        "BAS-DSR", "str", "Reporting", "Prefix used for daily site report numbers.",
    ),
    "standard_working_hours": (
        8.0, "float", "Workforce", "Standard working hours per shift, used for man-hour checks.",
    ),
}


def ensure_defaults():
    """Create any missing setting rows. Existing values are left untouched."""
    existing = {s.key for s in ProjectSetting.query.all()}
    created = 0
    for key, (default, vtype, category, description) in DEFAULT_SETTINGS.items():
        if key in existing:
            continue
        db.session.add(ProjectSetting(
            key=key, value=str(default), value_type=vtype,
            category=category, description=description,
        ))
        created += 1
    if created:
        db.session.commit()
    return created


def get(key, fallback=None):
    """Typed setting lookup with a fallback to the coded default."""
    row = ProjectSetting.query.filter_by(key=key).first()
    if row is not None:
        value = row.typed()
        if value is not None:
            return value
    if fallback is not None:
        return fallback
    spec = DEFAULT_SETTINGS.get(key)
    return spec[0] if spec else None


def set_value(key, value):
    row = ProjectSetting.query.filter_by(key=key).first()
    if row is None:
        spec = DEFAULT_SETTINGS.get(key, (None, "str", "General", ""))
        row = ProjectSetting(key=key, value_type=spec[1], category=spec[2], description=spec[3])
        db.session.add(row)
    row.value = "" if value is None else str(value)
    return row


def all_grouped():
    """Settings grouped by category, for the setup screen."""
    grouped = {}
    for row in ProjectSetting.query.order_by(ProjectSetting.category, ProjectSetting.key).all():
        grouped.setdefault(row.category or "General", []).append(row)
    return grouped
