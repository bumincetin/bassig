"""Dashboard assembly: where Bassignana is, what is late, what is blocking it,
what must happen next.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import func

from app import constants as C
from app.extensions import db
from app.models import (
    Blocker,
    DailyProgress,
    DailySiteReport,
    EquipmentEntry,
    WorkforceEntry,
)
from app.services import (
    data_health,
    procurement_service,
    progress,
    registers,
    schedule_service,
    settings,
)
from app.services.calculations import (
    elapsed_planned_pct,
    pct,
    safe_div,
    weighted_progress,
)


def _day_totals(day):
    row = db.session.query(
        func.coalesce(func.sum(DailyProgress.planned_quantity), 0.0),
        func.coalesce(func.sum(DailyProgress.actual_quantity), 0.0),
        func.coalesce(func.sum(DailyProgress.estimated_lost_hours), 0.0),
        func.count(DailyProgress.id),
    ).filter(DailyProgress.entry_date == day).one()
    planned, actual, lost, count = row
    return {
        "planned": float(planned or 0.0),
        "actual": float(actual or 0.0),
        "lost_hours_reported": float(lost or 0.0),
        "entries": int(count or 0),
        "achievement": pct(actual, planned),
    }


def workforce_today(day):
    rows = WorkforceEntry.query.filter_by(entry_date=day).all()
    by_discipline = defaultdict(int)
    by_contractor = defaultdict(int)
    for row in rows:
        by_discipline[row.discipline or "Other"] += row.workers or 0
        name = row.contractor.name if row.contractor else (row.contractor_name or "Unspecified")
        by_contractor[name] += row.workers or 0
    return {
        "total": sum(r.workers or 0 for r in rows),
        "man_hours": sum(r.man_hours for r in rows),
        "by_discipline": dict(sorted(by_discipline.items())),
        "by_contractor": dict(sorted(by_contractor.items())),
        "rows": rows,
    }


def equipment_today(day):
    rows = EquipmentEntry.query.filter_by(entry_date=day).all()
    working = sum(r.quantity or 0 for r in rows if (r.status or "").upper() == "WORKING")
    total_working_hours = sum(r.working_hours or 0.0 for r in rows)
    total_hours = sum(r.total_hours for r in rows)
    return {
        "rows": rows,
        "units": sum(r.quantity or 0 for r in rows),
        "active": working,
        "working_hours": total_working_hours,
        "lost_hours": sum(r.lost_hours for r in rows),
        "utilisation": pct(total_working_hours, total_hours),
    }


def workforce_trend(days=30, as_of=None):
    as_of = as_of or date.today()
    since = as_of - timedelta(days=days - 1)
    rows = (db.session.query(
        WorkforceEntry.entry_date,
        func.coalesce(func.sum(WorkforceEntry.workers), 0))
        .filter(WorkforceEntry.entry_date >= since, WorkforceEntry.entry_date <= as_of)
        .group_by(WorkforceEntry.entry_date)
        .order_by(WorkforceEntry.entry_date).all())
    return [{"date": d, "workers": int(w or 0)} for d, w in rows]


def productivity_trend(days=30, as_of=None):
    as_of = as_of or date.today()
    since = as_of - timedelta(days=days - 1)
    rows = (db.session.query(
        DailyProgress.entry_date,
        func.coalesce(func.sum(DailyProgress.planned_quantity), 0.0),
        func.coalesce(func.sum(DailyProgress.actual_quantity), 0.0))
        .filter(DailyProgress.entry_date >= since, DailyProgress.entry_date <= as_of)
        .group_by(DailyProgress.entry_date)
        .order_by(DailyProgress.entry_date).all())
    return [{"date": d, "planned": float(p or 0.0), "actual": float(a or 0.0),
             "achievement": pct(a, p)} for d, p, a in rows]


def equipment_utilisation_trend(days=30, as_of=None):
    as_of = as_of or date.today()
    since = as_of - timedelta(days=days - 1)
    rows = (db.session.query(
        EquipmentEntry.entry_date,
        func.coalesce(func.sum(EquipmentEntry.working_hours), 0.0),
        func.coalesce(func.sum(EquipmentEntry.idle_hours), 0.0),
        func.coalesce(func.sum(EquipmentEntry.breakdown_hours), 0.0))
        .filter(EquipmentEntry.entry_date >= since, EquipmentEntry.entry_date <= as_of)
        .group_by(EquipmentEntry.entry_date)
        .order_by(EquipmentEntry.entry_date).all())
    result = []
    for d, working, idle, breakdown in rows:
        total = float(working or 0) + float(idle or 0) + float(breakdown or 0)
        result.append({
            "date": d,
            "working": float(working or 0.0),
            "idle": float(idle or 0.0),
            "breakdown": float(breakdown or 0.0),
            "utilisation": pct(working, total),
        })
    return result


def progress_curve(as_of=None, points=14):
    """Contractual baseline vs current plan vs actual, sampled over time.

    The activities and their weights are read once and the whole curve is then
    computed in memory. Sampling the rollup service per point would re-query the
    programme a dozen times for a single page load.
    """
    as_of = as_of or date.today()
    baseline = progress.baseline_version()
    current = progress.governing_version()
    if baseline is None and current is None:
        return []

    start_b, finish_b = schedule_service.project_dates(baseline) if baseline else (None, None)
    start_c, finish_c = schedule_service.project_dates(current) if current else (None, None)
    starts = [d for d in (start_b, start_c) if d]
    finishes = [d for d in (finish_b, finish_c) if d]
    if not starts or not finishes:
        return []
    start, finish = min(starts), max(finishes)

    span = max((finish - start).days, 1)
    step = max(span // max(points - 1, 1), 1)
    samples = []
    cursor = start
    while cursor <= finish:
        samples.append(cursor)
        cursor = cursor + timedelta(days=step)
    if samples[-1] != finish:
        samples.append(finish)
    if start <= as_of <= finish and as_of not in samples:
        samples.append(as_of)
        samples.sort()

    basis = settings.get("progress_weight_basis", "DURATION DERIVED")
    completed_map = progress.completed_quantity_by_wbs(as_of)

    def _weighted(leaves, sample, use_baseline_dates):
        planned_items = []
        for activity, weight in leaves:
            if use_baseline_dates:
                first = activity.baseline_start or activity.plan_start
                last = activity.baseline_finish or activity.plan_finish
            else:
                first, last = activity.plan_start, activity.plan_finish
            planned = elapsed_planned_pct(first, last, sample)
            if planned is not None:
                planned_items.append((weight, planned))
        return weighted_progress(planned_items)

    baseline_leaves = [(a, progress.activity_weight(a, basis))
                       for a in progress.activities_for(baseline, only_leaves=True)] \
        if baseline else []
    current_leaves = [(a, progress.activity_weight(a, basis))
                      for a in progress.activities_for(current, only_leaves=True)] \
        if current else []

    # The actual percentage does not change with the sample date, so it is
    # computed once and shown only up to the reporting date.
    actual_items = []
    for activity, weight in current_leaves:
        value, _ = progress.activity_actual_pct(activity, completed_map)
        if value is not None:
            actual_items.append((weight, value))
    actual_now = weighted_progress(actual_items)

    series = []
    for sample in samples:
        series.append({
            "date": sample,
            "contractual": _weighted(baseline_leaves, sample, True) if baseline_leaves else None,
            "current_plan": _weighted(current_leaves, sample, False) if current_leaves else None,
            "actual": actual_now if sample == as_of else None,
        })
    return series


def build(as_of=None):
    """Everything the dashboard renders, computed once."""
    as_of = as_of or date.today()

    rows = schedule_service.comparison_rows(as_of)
    roll = progress.rollup(as_of=as_of)
    contractual_planned = progress.contractual_planned_pct(as_of)

    today = _day_totals(as_of)
    blockers = registers.blocker_summary()
    open_blockers = [b for b in Blocker.query.all()
                     if (b.status or "OPEN").upper() in C.ACTION_OPEN_STATES]
    lost_today = sum(b.effective_lost_hours for b in Blocker.query.filter_by(entry_date=as_of).all())

    quality = registers.quality_summary(as_of)
    rfi = registers.rfi_summary(as_of)
    issues = registers.issue_summary(as_of)
    permits = registers.permit_summary(as_of)
    procurement = procurement_service.procurement_warnings(as_of)
    acceptance = registers.overall_acceptance_readiness(as_of)

    critical = schedule_service.critical_rows(rows)
    at_risk = schedule_service.at_risk_rows(rows)
    overdue = schedule_service.overdue_rows(rows, as_of)
    milestones = schedule_service.upcoming_milestones(rows, 8, as_of)
    overdue_ms = schedule_service.overdue_milestones(rows, as_of)

    latest_report = (DailySiteReport.query
                     .order_by(DailySiteReport.report_date.desc()).first())

    health = data_health.report()

    return {
        "as_of": as_of,
        "rows": rows,
        "rollup": roll,
        "contractual_planned_pct": contractual_planned,
        "current_planned_pct": roll["overall_planned"],
        "actual_pct": roll["overall_actual"],
        "variance_vs_contractual": (
            None if (roll["overall_actual"] is None or contractual_planned is None)
            else roll["overall_actual"] - contractual_planned
        ),
        "variance_vs_current": roll["variance"],
        "today": today,
        "workforce": workforce_today(as_of),
        "equipment": equipment_today(as_of),
        "blockers": blockers,
        "open_blockers": open_blockers,
        "open_blocker_count": len(open_blockers),
        "lost_hours_today": lost_today or today["lost_hours_reported"],
        "quality": quality,
        "rfi": rfi,
        "issues": issues,
        "permits": permits,
        "procurement": procurement,
        "acceptance": acceptance,
        "critical": critical,
        "at_risk": at_risk,
        "overdue": overdue,
        "milestones": milestones,
        "overdue_milestones": overdue_ms,
        "critical_workfronts": schedule_service.critical_workfronts(rows),
        "area_progress": progress.progress_by_area(as_of),
        "latest_report": latest_report,
        "health": health,
        "reconciliation": data_health.reconciliation_flags(),
        "schedule_warnings": data_health.schedule_health(),
        "overdue_actions": (
            issues["overdue"] + quality["overdue_ncr"] + quality["overdue_punch"]
            + rfi["overdue"] + permits["overdue"]
        ),
    }


def charts(context):
    """JSON-serialisable chart payloads derived from a built dashboard context.

    Each trend is computed once; the previous version recomputed some of them
    per chart, which meant several identical scans of the daily records.
    """
    as_of = context["as_of"]
    curve = progress_curve(as_of)
    blockers = context["blockers"]
    productivity = productivity_trend(30, as_of)
    workforce = workforce_trend(30, as_of)
    equipment = equipment_utilisation_trend(30, as_of)
    stages = procurement_service.stage_distribution()
    return {
        "progress_curve": {
            "labels": [p["date"].isoformat() for p in curve],
            "contractual": [p["contractual"] for p in curve],
            "current_plan": [p["current_plan"] for p in curve],
            "actual": [p["actual"] for p in curve],
        },
        "by_work_package": {
            "labels": [r["name"] for r in context["rollup"]["by_work_package"]],
            "values": [r["progress"] for r in context["rollup"]["by_work_package"]],
        },
        "by_area": {
            "labels": [r["area_label"] for r in context["area_progress"]],
            "actual": [r["actual"] for r in context["area_progress"]],
            "planned": [r["planned"] for r in context["area_progress"]],
        },
        "productivity": {
            "labels": [p["date"].isoformat() for p in productivity],
            "planned": [p["planned"] for p in productivity],
            "actual": [p["actual"] for p in productivity],
        },
        "workforce": {
            "labels": [p["date"].isoformat() for p in workforce],
            "values": [p["workers"] for p in workforce],
        },
        "equipment": {
            "labels": [p["date"].isoformat() for p in equipment],
            "values": [p["utilisation"] for p in equipment],
        },
        "lost_hours": {
            "labels": [c["category"] for c in blockers["by_category"]],
            "values": [c["lost_hours"] for c in blockers["by_category"]],
        },
        "issues": {
            "labels": list(context["issues"]["by_category"].keys()),
            "values": list(context["issues"]["by_category"].values()),
        },
        "procurement": {
            "labels": [s["stage"] for s in stages],
            "values": [s["count"] for s in stages],
        },
        "quality": {
            "labels": list(context["quality"]["by_status"].keys()),
            "values": list(context["quality"]["by_status"].values()),
        },
        "milestones": {
            "labels": [m["name"][:44] for m in context["milestones"]],
            "values": [m["actual_pct"] or 0.0 for m in context["milestones"]],
        },
        "acceptance": {
            "labels": [f"Gate {v['gate'].gate_code} - {v['gate'].name}"
                       for v in context["acceptance"]["gates"]],
            "values": [v["readiness_pct"] or 0.0 for v in context["acceptance"]["gates"]],
        },
    }
