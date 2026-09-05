"""Schedule control: baseline / current comparison, variance, lookaheads.

The contractual baseline is read-only for comparison purposes. Importing an
updated programme creates a new schedule version and never writes into the
baseline version's rows.
"""
from __future__ import annotations

import re
from datetime import date, timedelta

from app import constants as C
from app.models import ScheduleVersion, WbsActivity
from app.services import progress, settings
from app.services.calculations import delay_days, elapsed_planned_pct, variance_pp
from app.services.status_rules import (
    activity_status,
    classify_schedule_variance,
    is_overdue_incomplete_milestone,
)

_NORMALISE = re.compile(r"[^a-z0-9]+")


def normalise_name(name):
    """Loose activity-name key used to match activities across revisions."""
    if not name:
        return ""
    return _NORMALISE.sub(" ", str(name).lower()).strip()


def build_baseline_index(baseline):
    """Index baseline activities by WBS code and by normalised name."""
    by_code, by_name = {}, {}
    if baseline is None:
        return by_code, by_name
    for activity in progress.activities_for(baseline):
        by_code[activity.wbs_code] = activity
        key = normalise_name(activity.activity_name)
        # First occurrence wins so a duplicated name cannot silently re-point.
        by_name.setdefault(key, activity)
    return by_code, by_name


def match_baseline(activity, by_code, by_name):
    """Find the baseline counterpart of a current-plan activity.

    Order: explicit manual link, then normalised activity name, then WBS code.
    WBS codes are renumbered between revisions on this project, so the name
    match is deliberately tried before the code match.
    """
    if activity.baseline_link_wbs:
        found = by_code.get(activity.baseline_link_wbs)
        if found:
            return found, "MANUAL LINK"
    found = by_name.get(normalise_name(activity.activity_name))
    if found:
        return found, "NAME"
    found = by_code.get(activity.wbs_code)
    if found:
        return found, "WBS CODE"
    return None, "UNMATCHED"


def comparison_rows(as_of=None, version=None, baseline=None):
    """Baseline vs current vs actual, one row per current-plan activity."""
    as_of = as_of or date.today()
    version = version or progress.governing_version()
    baseline = baseline if baseline is not None else progress.baseline_version()
    if version is None:
        return []

    by_code, by_name = build_baseline_index(baseline)
    completed_map = progress.completed_quantity_by_wbs(as_of)
    same_version = baseline is not None and version.id == baseline.id

    rows = []
    for activity in progress.activities_for(version):
        base, match_kind = (activity, "SELF") if same_version else match_baseline(activity, by_code, by_name)

        baseline_start = (base.baseline_start or base.plan_start) if base else None
        baseline_finish = (base.baseline_finish or base.plan_finish) if base else None

        actual_pct, actual_basis = progress.activity_actual_pct(activity, completed_map)
        planned_pct = elapsed_planned_pct(activity.plan_start, activity.plan_finish, as_of)
        contractual_planned_pct = elapsed_planned_pct(baseline_start, baseline_finish, as_of)

        overdue_ms = is_overdue_incomplete_milestone(activity, as_of)
        variance = variance_pp(actual_pct, planned_pct)
        contractual_variance = variance_pp(actual_pct, contractual_planned_pct)

        rows.append({
            "activity": activity,
            "baseline_activity": base if not same_version else None,
            "match_kind": match_kind,
            "wbs_code": activity.wbs_code,
            "name": activity.activity_name,
            "work_package": activity.work_package,
            "discipline": activity.discipline,
            "level": activity.level,
            "is_milestone": activity.is_milestone,
            "baseline_start": baseline_start,
            "baseline_finish": baseline_finish,
            "plan_start": activity.plan_start,
            "plan_finish": activity.plan_finish,
            "actual_start": activity.actual_start,
            "actual_finish": activity.actual_finish,
            "planned_pct": planned_pct,
            "contractual_planned_pct": contractual_planned_pct,
            "actual_pct": actual_pct,
            "actual_basis": actual_basis,
            "variance": variance,
            "contractual_variance": contractual_variance,
            "start_delay_days": delay_days(baseline_start, activity.plan_start),
            "finish_delay_days": delay_days(baseline_finish, activity.plan_finish),
            "classification": classify_schedule_variance(variance, overdue_ms),
            "overdue_milestone": overdue_ms,
            "status": activity_status(activity, as_of),
        })
    return rows


# --------------------------------------------------------------------------
# Filtered views
# --------------------------------------------------------------------------
def _incomplete(row):
    return (row["actual_pct"] or 0.0) < 100.0 and row["status"] != "COMPLETE"


def critical_rows(rows):
    return [r for r in rows if r["classification"] == C.SCHEDULE_CLASS_CRITICAL and _incomplete(r)]


def at_risk_rows(rows):
    return [r for r in rows if r["classification"] == C.SCHEDULE_CLASS_AT_RISK and _incomplete(r)]


def overdue_rows(rows, as_of=None):
    as_of = as_of or date.today()
    return [r for r in rows
            if r["plan_finish"] and r["plan_finish"] < as_of and _incomplete(r)]


def late_start_rows(rows, as_of=None):
    as_of = as_of or date.today()
    return [r for r in rows
            if r["plan_start"] and r["plan_start"] < as_of
            and not r["actual_start"] and (r["actual_pct"] or 0.0) <= 0.0]


def starting_within(rows, days=None, as_of=None):
    as_of = as_of or date.today()
    days = days if days is not None else settings.get("imminent_window_days", 7)
    horizon = as_of + timedelta(days=int(days))
    return [r for r in rows
            if r["plan_start"] and as_of <= r["plan_start"] <= horizon and not r["actual_start"]]


def finishing_within(rows, days=None, as_of=None):
    as_of = as_of or date.today()
    days = days if days is not None else settings.get("imminent_window_days", 7)
    horizon = as_of + timedelta(days=int(days))
    return [r for r in rows
            if r["plan_finish"] and as_of <= r["plan_finish"] <= horizon and _incomplete(r)]


def lookahead(rows, weeks=2, as_of=None):
    """Activities active or starting inside the lookahead window."""
    as_of = as_of or date.today()
    horizon = as_of + timedelta(weeks=int(weeks))
    result = []
    for row in rows:
        start, finish = row["plan_start"], row["plan_finish"]
        if not start and not finish:
            continue
        window_start = start or finish
        window_finish = finish or start
        if window_start <= horizon and window_finish >= as_of and _incomplete(row):
            result.append(row)
    result.sort(key=lambda r: (r["plan_start"] or date.max, r["wbs_code"]))
    return result


def upcoming_milestones(rows, limit=10, as_of=None):
    as_of = as_of or date.today()
    milestones = [r for r in rows if r["is_milestone"] and _incomplete(r)]
    milestones.sort(key=lambda r: (r["plan_finish"] or r["plan_start"] or date.max))
    return milestones[:limit]


def overdue_milestones(rows, as_of=None):
    return [r for r in rows if r["overdue_milestone"]]


def unmatched_to_baseline(rows):
    return [r for r in rows if r["match_kind"] == "UNMATCHED"]


def critical_workfronts(rows, limit=10):
    """Work packages carrying the largest negative variance."""
    buckets = {}
    for row in rows:
        if row["variance"] is None or not _incomplete(row):
            continue
        key = row["work_package"] or "Unassigned"
        entry = buckets.setdefault(key, {"work_package": key, "variance_sum": 0.0, "count": 0,
                                         "critical": 0})
        entry["variance_sum"] += row["variance"]
        entry["count"] += 1
        if row["classification"] == C.SCHEDULE_CLASS_CRITICAL:
            entry["critical"] += 1
    results = []
    for entry in buckets.values():
        entry["average_variance"] = entry["variance_sum"] / entry["count"] if entry["count"] else None
        results.append(entry)
    results.sort(key=lambda e: (e["average_variance"] if e["average_variance"] is not None else 0.0))
    return results[:limit]


def recovery_comparison(as_of=None):
    """Compare every non-baseline schedule version against the baseline."""
    as_of = as_of or date.today()
    baseline = progress.baseline_version()
    if baseline is None:
        return []
    by_code, by_name = build_baseline_index(baseline)
    results = []
    for version in (ScheduleVersion.query
                    .filter(ScheduleVersion.id != baseline.id)
                    .order_by(ScheduleVersion.effective_date, ScheduleVersion.id).all()):
        finish_deltas, start_deltas, unmatched = [], [], 0
        for activity in progress.activities_for(version):
            base, kind = match_baseline(activity, by_code, by_name)
            if base is None:
                unmatched += 1
                continue
            bf = base.baseline_finish or base.plan_finish
            bs = base.baseline_start or base.plan_start
            fd = delay_days(bf, activity.plan_finish)
            sd = delay_days(bs, activity.plan_start)
            if fd is not None:
                finish_deltas.append(fd)
            if sd is not None:
                start_deltas.append(sd)
        results.append({
            "version": version,
            "activities": len(progress.activities_for(version)),
            "unmatched": unmatched,
            "max_finish_slip": max(finish_deltas) if finish_deltas else None,
            "avg_finish_slip": (sum(finish_deltas) / len(finish_deltas)) if finish_deltas else None,
            "avg_start_slip": (sum(start_deltas) / len(start_deltas)) if start_deltas else None,
            "project_finish": max((a.plan_finish for a in progress.activities_for(version)
                                   if a.plan_finish), default=None),
        })
    return results


def project_dates(version):
    """Earliest start and latest finish of a version."""
    activities = progress.activities_for(version)
    starts = [a.plan_start or a.baseline_start for a in activities if (a.plan_start or a.baseline_start)]
    finishes = [a.plan_finish or a.baseline_finish for a in activities if (a.plan_finish or a.baseline_finish)]
    return (min(starts) if starts else None, max(finishes) if finishes else None)
