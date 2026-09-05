"""Simple production-rate forecasting.

No machine learning and no statistical modelling: the forecast is the arithmetic
mean of recent actual production on active working days. It is labelled as a
simple production-rate forecast everywhere it is shown, and is never presented
as a contractual date.
"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import func

from app import constants as C
from app.extensions import db
from app.i18n import translate as t
from app.models import DailyProgress, WbsActivity
from app.services import progress, settings
from app.services.calculations import forecast_finish_date, forecast_remaining, production_rate

INSUFFICIENT = "Not enough production history to calculate forecast."
LABEL = "Simple production-rate forecast"


def daily_actuals(wbs_code, since=None, until=None):
    """Actual quantity per calendar day for one WBS code."""
    query = db.session.query(
        DailyProgress.entry_date,
        func.coalesce(func.sum(DailyProgress.actual_quantity), 0.0),
    ).filter(DailyProgress.wbs_code == wbs_code)
    if since:
        query = query.filter(DailyProgress.entry_date >= since)
    if until:
        query = query.filter(DailyProgress.entry_date <= until)
    rows = query.group_by(DailyProgress.entry_date).order_by(DailyProgress.entry_date).all()
    return [(d, float(q or 0.0)) for d, q in rows]


def forecast_for_activity(activity, as_of=None, window_days=None):
    """Production-rate forecast for one quantity-based activity."""
    as_of = as_of or date.today()
    window_days = int(window_days or settings.get("forecast_window_short_days", 7))
    min_days = int(settings.get("forecast_min_working_days", 3))

    total_required = activity.total_required_quantity
    completed_map = progress.completed_quantity_by_wbs(as_of)
    completed = completed_map.get(activity.wbs_code, 0.0)

    result = {
        "activity": activity,
        "label": LABEL,
        "window_days": window_days,
        "total_required": total_required,
        "completed": completed,
        "remaining": None,
        "rate": None,
        "active_days": 0,
        "working_days_remaining": None,
        "forecast_finish": None,
        "message": None,
        "unit": activity.unit,
    }

    if not total_required:
        result["message"] = t("{data_required}: total required quantity for {code}.",
                              data_required=t(C.DATA_REQUIRED), code=activity.wbs_code)
        return result

    since = as_of - timedelta(days=window_days - 1)
    quantities = [q for _, q in daily_actuals(activity.wbs_code, since=since, until=as_of)]
    rate, active_days = production_rate(quantities)
    result["rate"] = rate
    result["active_days"] = active_days

    remaining, days_remaining = forecast_remaining(total_required, completed, rate)
    result["remaining"] = remaining

    if active_days < min_days or not rate:
        result["message"] = INSUFFICIENT
        return result

    result["working_days_remaining"] = days_remaining
    result["forecast_finish"] = forecast_finish_date(as_of, days_remaining)
    return result


def forecast_table(as_of=None, window_days=None, version=None):
    """Forecast every quantity-based activity in the governing programme."""
    as_of = as_of or date.today()
    version = version or progress.governing_version()
    if version is None:
        return []
    rows = []
    for activity in progress.activities_for(version, only_leaves=True):
        if (activity.progress_method or "").upper() != "QUANTITY":
            continue
        rows.append(forecast_for_activity(activity, as_of, window_days))
    rows.sort(key=lambda r: (r["forecast_finish"] or date.max, r["activity"].wbs_code))
    return rows


def quantity_based_activities(version=None):
    version = version or progress.governing_version()
    if version is None:
        return []
    return [a for a in progress.activities_for(version, only_leaves=True)
            if (a.progress_method or "").upper() == "QUANTITY"]
