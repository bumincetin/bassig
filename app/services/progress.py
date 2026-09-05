"""Progress measurement and weighted rollup.

Two measurement methods are supported:

* QUANTITY -- completed quantity / total required quantity
* WEIGHTED / MANUAL -- reported percentage carrying an explicit weight

Rollup runs over leaf activities only, so a summary line never double counts
its children. Project progress is never a simple mean of activity percentages.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date

from sqlalchemy import func

from app import constants as C
from app.extensions import db
from app.i18n import translate as t
from app.models import DailyProgress, ScheduleVersion, WbsActivity
from app.services import settings
from app.services.calculations import (
    elapsed_planned_pct,
    quantity_progress_pct,
    variance_pp,
    weighted_progress,
)


# --------------------------------------------------------------------------
# Schedule version helpers
# --------------------------------------------------------------------------
def baseline_version():
    return (ScheduleVersion.query
            .filter_by(is_contractual_baseline=True)
            .order_by(ScheduleVersion.effective_date.desc(), ScheduleVersion.id.desc())
            .first())


def current_version():
    """The working programme that governs execution, if one is registered."""
    version = (ScheduleVersion.query
               .filter_by(is_current_working=True)
               .order_by(ScheduleVersion.effective_date.desc(), ScheduleVersion.id.desc())
               .first())
    return version or baseline_version()


def governing_version():
    """Version used for operational planning (lookaheads, dashboards)."""
    preference = settings.get("governing_schedule", "CURRENT WORKING")
    if str(preference).upper() == "CONTRACTUAL BASELINE":
        return baseline_version() or current_version()
    return current_version()


def activities_for(version, only_leaves=False):
    if version is None:
        return []
    rows = (WbsActivity.query
            .filter_by(schedule_version_id=version.id)
            .order_by(WbsActivity.sort_index, WbsActivity.wbs_code)
            .all())
    if not only_leaves:
        return rows
    parents = {r.parent_wbs_code for r in rows if r.parent_wbs_code}
    return [r for r in rows if r.wbs_code not in parents]


def leaf_codes(version):
    rows = activities_for(version)
    parents = {r.parent_wbs_code for r in rows if r.parent_wbs_code}
    return {r.wbs_code for r in rows if r.wbs_code not in parents}


# --------------------------------------------------------------------------
# Actual quantity aggregation
# --------------------------------------------------------------------------
def rebase_cumulatives(wbs_code):
    """Recompute the running totals of one WBS code across every day.

    Entering a day out of order -- catching up last week on Monday, or
    correcting a figure after later days exist -- would otherwise leave the
    later rows carrying a running total that no longer matches the days before
    them. Rebasing keeps the chain correct whatever order the days are entered
    in.
    """
    if not wbs_code:
        return 0
    rows = (DailyProgress.query
            .filter(DailyProgress.wbs_code == wbs_code)
            .order_by(DailyProgress.entry_date, DailyProgress.id).all())
    running, changed = 0.0, 0
    for row in rows:
        if row.cumulative_before != running:
            row.cumulative_before = running
            changed += 1
        running += float(row.actual_quantity or 0.0)
    return changed


def rebase_all_cumulatives():
    """Rebase every WBS code. Used after a bulk change."""
    codes = [code for (code,) in db.session.query(DailyProgress.wbs_code)
             .filter(DailyProgress.wbs_code.isnot(None)).distinct().all()]
    return sum(rebase_cumulatives(code) for code in codes)


def completed_quantity_by_wbs(as_of=None):
    """Cumulative actual quantity recorded per WBS code up to `as_of`."""
    query = db.session.query(
        DailyProgress.wbs_code,
        func.coalesce(func.sum(DailyProgress.actual_quantity), 0.0),
    )
    if as_of:
        query = query.filter(DailyProgress.entry_date <= as_of)
    return {code: float(total or 0.0) for code, total in query.group_by(DailyProgress.wbs_code).all()}


# --------------------------------------------------------------------------
# Per-activity progress
# --------------------------------------------------------------------------
def activity_actual_pct(activity, completed_map=None):
    """Actual percentage of one activity, with the basis used.

    Returns (percent, basis) where basis is one of QUANTITY, MANUAL or
    the DATA REQUIRED marker.
    """
    method = (activity.progress_method or "MANUAL").upper()
    if method == "QUANTITY":
        total = activity.total_required_quantity
        if not total:
            return None, C.DATA_REQUIRED
        completed = (completed_map or {}).get(activity.wbs_code, 0.0)
        return quantity_progress_pct(completed, total), "QUANTITY"
    value = activity.reported_completion_pct
    if value is None:
        return None, C.DATA_REQUIRED
    return max(0.0, min(float(value), 100.0)), "MANUAL"


def activity_weight(activity, basis=None):
    """Weight of one activity under the configured weighting basis."""
    basis = (basis or settings.get("progress_weight_basis", "DURATION DERIVED")).upper()
    if basis == "APPROVED WEIGHT":
        if (activity.weight_basis or "").upper() == "APPROVED WEIGHT" and activity.progress_weight:
            return float(activity.progress_weight)
        return 0.0
    if basis == "QUANTITY":
        return float(activity.total_required_quantity or 0.0)
    # DURATION DERIVED: milestones carry no duration, so they get a nominal
    # weight of 1 calendar day rather than being silently dropped.
    duration = activity.duration_days
    if duration is None:
        return 1.0
    return max(float(duration), 1.0)


def weighting_basis_report():
    """Describe which weighting basis is in force and whether it is approved."""
    basis = str(settings.get("progress_weight_basis", "DURATION DERIVED")).upper()
    approved_count = (WbsActivity.query
                      .filter(WbsActivity.weight_basis == "APPROVED WEIGHT")
                      .filter(WbsActivity.progress_weight.isnot(None))
                      .count())
    return {
        "basis": basis,
        "approved_weight_count": approved_count,
        "is_approved": basis == "APPROVED WEIGHT" and approved_count > 0,
        "warning": None if (basis == "APPROVED WEIGHT" and approved_count > 0) else (
            t("{data_required}: approved progress-weight register. Rollup is computed on a "
              "{basis} basis and is not a contractual measurement.",
              data_required=t(C.DATA_REQUIRED), basis=t(basis))
        ),
    }


# --------------------------------------------------------------------------
# Rollups
# --------------------------------------------------------------------------
def rollup(version=None, as_of=None, basis=None):
    """Weighted progress rollup for a schedule version.

    Returns a dict with overall progress plus breakdowns by work package,
    discipline and (through daily records) area.
    """
    version = version or governing_version()
    as_of = as_of or date.today()
    if version is None:
        return {
            "version": None,
            "overall_actual": None,
            "overall_planned": None,
            "variance": None,
            "by_work_package": [],
            "by_discipline": [],
            "basis": weighting_basis_report(),
            "leaf_count": 0,
        }

    completed_map = completed_quantity_by_wbs(as_of)
    leaves = activities_for(version, only_leaves=True)
    basis = basis or settings.get("progress_weight_basis", "DURATION DERIVED")

    weighted_actual = []
    weighted_planned = []
    package_items = defaultdict(list)
    discipline_items = defaultdict(list)

    for activity in leaves:
        weight = activity_weight(activity, basis)
        actual, _ = activity_actual_pct(activity, completed_map)
        planned = elapsed_planned_pct(activity.plan_start, activity.plan_finish, as_of)
        if actual is not None:
            weighted_actual.append((weight, actual))
            package_items[activity.work_package or "Unassigned"].append((weight, actual))
            discipline_items[activity.discipline or "Unassigned"].append((weight, actual))
        if planned is not None:
            weighted_planned.append((weight, planned))

    overall_actual = weighted_progress(weighted_actual)
    overall_planned = weighted_progress(weighted_planned)

    by_package = sorted(
        ({"name": name, "progress": weighted_progress(items), "count": len(items)}
         for name, items in package_items.items()),
        key=lambda r: r["name"],
    )
    by_discipline = sorted(
        ({"name": name, "progress": weighted_progress(items), "count": len(items)}
         for name, items in discipline_items.items()),
        key=lambda r: r["name"],
    )

    return {
        "version": version,
        "overall_actual": overall_actual,
        "overall_planned": overall_planned,
        "variance": variance_pp(overall_actual, overall_planned),
        "by_work_package": by_package,
        "by_discipline": by_discipline,
        "basis": weighting_basis_report(),
        "leaf_count": len(leaves),
    }


def contractual_planned_pct(as_of=None, basis=None):
    """Weighted planned percentage against the contractual baseline dates."""
    version = baseline_version()
    if version is None:
        return None
    as_of = as_of or date.today()
    basis = basis or settings.get("progress_weight_basis", "DURATION DERIVED")
    items = []
    for activity in activities_for(version, only_leaves=True):
        start = activity.baseline_start or activity.plan_start
        finish = activity.baseline_finish or activity.plan_finish
        planned = elapsed_planned_pct(start, finish, as_of)
        if planned is not None:
            items.append((activity_weight(activity, basis), planned))
    return weighted_progress(items)


def progress_by_area(as_of=None):
    """Actual quantity delivered per area, from daily records only."""
    query = db.session.query(
        DailyProgress.area_id,
        func.coalesce(func.sum(DailyProgress.actual_quantity), 0.0),
        func.coalesce(func.sum(DailyProgress.planned_quantity), 0.0),
        func.count(DailyProgress.id),
    )
    if as_of:
        query = query.filter(DailyProgress.entry_date <= as_of)
    rows = query.group_by(DailyProgress.area_id).all()
    from app.models import Area
    areas = {a.id: a for a in Area.query.all()}
    result = []
    for area_id, actual, planned, count in rows:
        area = areas.get(area_id)
        result.append({
            "area": area,
            "area_label": area.label if area else "Not allocated to an area",
            "actual": float(actual or 0.0),
            "planned": float(planned or 0.0),
            "entries": count,
        })
    result.sort(key=lambda r: r["area_label"])
    return result
