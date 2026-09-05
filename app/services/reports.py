"""Daily site report and weekly project-control report.

Every narrative line is generated from counted facts. There is no generated
prose, no language model and no interpretation.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import func

from app import constants as C
from app.extensions import db
from app.i18n import translate as t
from app.models import (
    Blocker,
    DailyProgress,
    DailySiteReport,
    Delivery,
    EquipmentEntry,
    Project,
    QualityRecord,
    SiteObservation,
    WorkforceEntry,
)
from app.services import (
    dashboard,
    procurement_service,
    progress,
    registers,
    schedule_service,
    settings,
)
from app.services.calculations import pct
from app.services.status_rules import quality_status, rfi_status


def week_bounds(reference=None):
    """Monday-to-Sunday bounds of the week containing `reference`."""
    reference = reference or date.today()
    start = reference - timedelta(days=reference.weekday())
    return start, start + timedelta(days=6)


# --------------------------------------------------------------------------
# Daily report
# --------------------------------------------------------------------------
def daily_report(report_date):
    report = DailySiteReport.query.filter_by(report_date=report_date).first()

    progress_rows = (DailyProgress.query
                     .filter_by(entry_date=report_date)
                     .order_by(DailyProgress.wbs_code).all())
    workforce_rows = WorkforceEntry.query.filter_by(entry_date=report_date).all()
    equipment_rows = EquipmentEntry.query.filter_by(entry_date=report_date).all()
    observation_rows = (SiteObservation.query
                        .filter_by(entry_date=report_date)
                        .order_by(SiteObservation.severity.desc()).all())
    blocker_rows = Blocker.query.filter_by(entry_date=report_date).all()
    delivery_rows = Delivery.query.filter_by(delivery_date=report_date).all()
    inspection_rows = QualityRecord.query.filter_by(record_date=report_date).all()

    planned = sum(r.planned_quantity or 0.0 for r in progress_rows)
    actual = sum(r.actual_quantity or 0.0 for r in progress_rows)

    by_discipline = defaultdict(lambda: {"workers": 0, "hours": 0.0, "man_hours": 0.0})
    for row in workforce_rows:
        bucket = by_discipline[row.discipline or "Other"]
        bucket["workers"] += row.workers or 0
        bucket["hours"] += row.hours or 0.0
        bucket["man_hours"] += row.man_hours

    by_contractor = defaultdict(int)
    for row in workforce_rows:
        name = (row.contractor.name if row.contractor
                else (row.contractor_name or t("Unspecified")))
        by_contractor[name] += row.workers or 0

    by_area = defaultdict(lambda: {"planned": 0.0, "actual": 0.0, "entries": 0})
    for row in progress_rows:
        key = row.area.label if row.area else t("Not allocated to an area")
        bucket = by_area[key]
        bucket["planned"] += row.planned_quantity or 0.0
        bucket["actual"] += row.actual_quantity or 0.0
        bucket["entries"] += 1

    rollup = progress.rollup(as_of=report_date)
    contractual = progress.contractual_planned_pct(report_date)
    schedule_rows = schedule_service.comparison_rows(report_date)

    below_target = [r for r in progress_rows
                    if r.achievement_pct is not None and r.achievement_pct < 100.0]
    open_critical_blockers = [b for b in Blocker.query.all()
                              if (b.status or "OPEN").upper() in C.ACTION_OPEN_STATES
                              and b.effective_lost_hours >= 4.0]
    lost_by_cause = defaultdict(float)
    for blocker in blocker_rows:
        lost_by_cause[blocker.category or "Other"] += blocker.effective_lost_hours
    largest_cause = max(lost_by_cause.items(), key=lambda kv: kv[1]) if lost_by_cause else None

    overdue_quality = [r for r in QualityRecord.query.all()
                       if quality_status(r, report_date) == "OVERDUE"]
    procurement = procurement_service.procurement_warnings(report_date)
    shortages = [v for v in procurement["shortages"] if v["stock_status"] == C.STOCK_SHORTAGE]
    milestones = schedule_service.upcoming_milestones(schedule_rows, 5, report_date)
    rfis = registers.rfi_summary(report_date)

    # Deterministic summary: counted facts only.
    summary = []
    summary.append(t("Active workfronts reporting progress: {count}.", count=len(by_area)))
    achievement = pct(actual, planned)
    if achievement is None:
        summary.append(t("Daily achievement: no planned quantity was recorded for this date."))
    else:
        summary.append(t("Daily achievement: {percent}% ({actual} actual against {planned} planned).",
                         percent=f"{achievement:.1f}", actual=f"{actual:g}", planned=f"{planned:g}"))
    summary.append(t("Activities below the daily target: {below} of {total}.",
                     below=len(below_target), total=len(progress_rows)))
    summary.append(t("Open critical blockers (4 or more lost hours): {count}.",
                     count=len(open_critical_blockers)))
    summary.append(t("Late procurement packages: {late}; material shortages: {short}.",
                     late=procurement["late_count"], short=len(shortages)))
    summary.append(t("Overdue NCR / Punch List items: {count}.", count=len(overdue_quality)))
    if largest_cause:
        summary.append(t("Largest cause of lost hours today: {cause} ({hours} h).",
                         cause=t(largest_cause[0]), hours=f"{largest_cause[1]:g}"))
    else:
        summary.append(t("No lost hours were recorded against a blocker today."))
    if milestones:
        next_ms = milestones[0]
        summary.append(t("Next schedule milestone: {name} ({date}).", name=next_ms["name"],
                         date=(next_ms["plan_finish"] or next_ms["plan_start"]
                               or t("date not set"))))
    else:
        summary.append(t("No incomplete milestone is registered in the governing programme."))

    return {
        "project": Project.query.first(),
        "report": report,
        "report_date": report_date,
        "progress_rows": progress_rows,
        "workforce_rows": workforce_rows,
        "equipment_rows": equipment_rows,
        "observation_rows": observation_rows,
        "blocker_rows": blocker_rows,
        "delivery_rows": delivery_rows,
        "inspection_rows": inspection_rows,
        "photos": report.photos if report else [],
        "planned_quantity": planned,
        "actual_quantity": actual,
        "achievement": achievement,
        "by_discipline": dict(sorted(by_discipline.items())),
        "by_contractor": dict(sorted(by_contractor.items())),
        "by_area": dict(sorted(by_area.items())),
        "total_workers": sum(r.workers or 0 for r in workforce_rows),
        "total_man_hours": sum(r.man_hours for r in workforce_rows),
        "equipment_units": sum(r.quantity or 0 for r in equipment_rows),
        "equipment_lost_hours": sum(r.lost_hours for r in equipment_rows),
        "lost_hours": sum(b.effective_lost_hours for b in blocker_rows),
        "lost_by_cause": dict(sorted(lost_by_cause.items(), key=lambda kv: -kv[1])),
        "rollup": rollup,
        "contractual_planned_pct": contractual,
        "cumulative_actual_pct": rollup["overall_actual"],
        "shortages": shortages,
        "procurement": procurement,
        "overdue_quality": overdue_quality,
        "open_quality": [r for r in QualityRecord.query.all()
                         if (r.status or "").upper() in C.QUALITY_OPEN_STATES],
        "rfis": rfis,
        "milestones": milestones,
        "critical_activities": schedule_service.critical_rows(schedule_rows)[:10],
        "lookahead": schedule_service.lookahead(schedule_rows, 1, report_date)[:15],
        "summary": summary,
    }


# --------------------------------------------------------------------------
# Weekly report
# --------------------------------------------------------------------------
def weekly_report(week_start=None):
    week_start, week_end = week_bounds(week_start)
    previous_start = week_start - timedelta(days=7)

    rollup = progress.rollup(as_of=week_end)
    contractual = progress.contractual_planned_pct(week_end)
    rows = schedule_service.comparison_rows(week_end)

    week_totals = db.session.query(
        func.coalesce(func.sum(DailyProgress.planned_quantity), 0.0),
        func.coalesce(func.sum(DailyProgress.actual_quantity), 0.0),
        func.count(DailyProgress.id),
    ).filter(DailyProgress.entry_date.between(week_start, week_end)).one()

    previous_totals = db.session.query(
        func.coalesce(func.sum(DailyProgress.planned_quantity), 0.0),
        func.coalesce(func.sum(DailyProgress.actual_quantity), 0.0),
    ).filter(DailyProgress.entry_date.between(previous_start, week_start - timedelta(days=1))).one()

    workforce = (db.session.query(
        WorkforceEntry.entry_date, func.coalesce(func.sum(WorkforceEntry.workers), 0))
        .filter(WorkforceEntry.entry_date.between(week_start, week_end))
        .group_by(WorkforceEntry.entry_date)
        .order_by(WorkforceEntry.entry_date).all())

    productivity = dashboard.productivity_trend(
        (week_end - week_start).days + 1, week_end)

    blockers = registers.blocker_summary(week_start, week_end)
    quality = registers.quality_summary(week_end)
    rfi = registers.rfi_summary(week_end)
    permits = registers.permit_summary(week_end)
    procurement = procurement_service.procurement_warnings(week_end)
    acceptance = registers.overall_acceptance_readiness(week_end)

    short_weeks = int(settings.get("lookahead_short_weeks", 2))
    lookahead_rows = schedule_service.lookahead(rows, short_weeks, week_end)
    critical = schedule_service.critical_rows(rows)
    overdue = schedule_service.overdue_rows(rows, week_end)
    late_start = schedule_service.late_start_rows(rows, week_end)

    upcoming_tests = [r for r in rows
                      if r["work_package"] and "test" in (r["work_package"] or "").lower()
                      and r["plan_start"] and week_end <= r["plan_start"]
                      <= week_end + timedelta(weeks=short_weeks)]

    # Top actions for next week, ranked by contractual consequence.
    actions = []
    for row in overdue[:5]:
        actions.append(f"Recover overdue activity {row['wbs_code']} {row['name']} "
                       f"(planned finish {row['plan_finish']}).")
    for row in late_start[:5]:
        actions.append(f"Start {row['wbs_code']} {row['name']} "
                       f"(planned start {row['plan_start']}, not yet started).")
    for package in procurement["late_packages"][:5]:
        actions.append(f"Escalate late procurement package {package.package_code} "
                       f"{package.package_name}.")
    for view in procurement["shortages"][:5]:
        actions.append(f"Resolve material shortage: {view['material'].item}.")
    for record in registers.overdue_quality("NCR", week_end)[:5]:
        actions.append(f"Close overdue NCR {record.record_number}: {record.title or ''}".strip())
    for record in registers.overdue_quality("PUNCH LIST", week_end)[:5]:
        actions.append(f"Close overdue Punch List item {record.record_number}.")
    for rfi_row in registers.overdue_rfis(week_end)[:5]:
        actions.append(f"Chase overdue RFI {rfi_row.rfi_number}: {rfi_row.subject}.")

    return {
        "project": Project.query.first(),
        "week_start": week_start,
        "week_end": week_end,
        "rollup": rollup,
        "contractual_planned_pct": contractual,
        "variance_vs_contractual": (
            None if (rollup["overall_actual"] is None or contractual is None)
            else rollup["overall_actual"] - contractual
        ),
        "week_planned": float(week_totals[0] or 0.0),
        "week_actual": float(week_totals[1] or 0.0),
        "week_entries": int(week_totals[2] or 0),
        "week_achievement": pct(week_totals[1], week_totals[0]),
        "previous_planned": float(previous_totals[0] or 0.0),
        "previous_actual": float(previous_totals[1] or 0.0),
        "workforce_trend": [{"date": d, "workers": int(w or 0)} for d, w in workforce],
        "workforce_peak": max((int(w or 0) for _, w in workforce), default=0),
        "productivity": productivity,
        "lookahead": lookahead_rows,
        "lookahead_weeks": short_weeks,
        "critical": critical,
        "overdue": overdue,
        "late_start": late_start,
        "blockers": blockers,
        "quality": quality,
        "rfi": rfi,
        "permits": permits,
        "procurement": procurement,
        "acceptance": acceptance,
        "upcoming_tests": upcoming_tests,
        "milestones": schedule_service.upcoming_milestones(rows, 10, week_end),
        "actions": actions,
        "deliveries": Delivery.query.filter(
            Delivery.delivery_date.between(week_start, week_end)).all(),
        "reports_filed": DailySiteReport.query.filter(
            DailySiteReport.report_date.between(week_start, week_end)).count(),
    }
