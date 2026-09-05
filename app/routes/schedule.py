"""Schedule & WBS control."""
from __future__ import annotations

from datetime import date

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from app import constants as C
from app.extensions import db
from app.i18n import translate as t
from app.models import ScheduleVersion, SourceDocument, WbsActivity
from app.routes._helpers import (
    arg_int,
    arg_str,
    csv_response,
    form_bool,
    form_date,
    form_float,
    form_int,
    form_str,
    request_date,
)
from app.services import exporters, progress, schedule_service, settings

bp = Blueprint("schedule", __name__, url_prefix="/schedule")


@bp.route("/")
def index():
    as_of = request_date("as_of")
    version_id = arg_int("version")
    version = (db.session.get(ScheduleVersion, version_id) if version_id
               else progress.governing_version())
    baseline = progress.baseline_version()

    rows = schedule_service.comparison_rows(as_of, version=version, baseline=baseline)

    classification = arg_str("classification")
    work_package = arg_str("work_package")
    discipline = arg_str("discipline")
    view = arg_str("view", "all")
    search = arg_str("q")

    filtered = rows
    if classification:
        filtered = [r for r in filtered if r["classification"] == classification]
    if work_package:
        filtered = [r for r in filtered if r["work_package"] == work_package]
    if discipline:
        filtered = [r for r in filtered if r["discipline"] == discipline]
    if search:
        needle = search.lower()
        filtered = [r for r in filtered
                    if needle in (r["name"] or "").lower() or needle in (r["wbs_code"] or "").lower()]
    if view == "milestones":
        filtered = [r for r in filtered if r["is_milestone"]]
    elif view == "overdue":
        filtered = schedule_service.overdue_rows(filtered, as_of)
    elif view == "late_start":
        filtered = schedule_service.late_start_rows(filtered, as_of)
    elif view == "unmatched":
        filtered = schedule_service.unmatched_to_baseline(filtered)

    return render_template(
        "schedule/index.html",
        as_of=as_of,
        version=version,
        baseline=baseline,
        versions=ScheduleVersion.query.order_by(ScheduleVersion.schedule_type,
                                                ScheduleVersion.effective_date).all(),
        rows=filtered,
        all_rows=rows,
        work_packages=sorted({r["work_package"] for r in rows if r["work_package"]}),
        disciplines=sorted({r["discipline"] for r in rows if r["discipline"]}),
        counts={
            "total": len(rows),
            "critical": len(schedule_service.critical_rows(rows)),
            "at_risk": len(schedule_service.at_risk_rows(rows)),
            "overdue": len(schedule_service.overdue_rows(rows, as_of)),
            "late_start": len(schedule_service.late_start_rows(rows, as_of)),
            "unmatched": len(schedule_service.unmatched_to_baseline(rows)),
            "milestones": sum(1 for r in rows if r["is_milestone"]),
        },
        filters={"classification": classification, "work_package": work_package,
                 "discipline": discipline, "view": view, "q": search},
    )


@bp.route("/lookahead")
def lookahead():
    as_of = request_date("as_of")
    rows = schedule_service.comparison_rows(as_of)
    short_weeks = int(settings.get("lookahead_short_weeks", 2))
    long_weeks = int(settings.get("lookahead_long_weeks", 4))
    window = int(settings.get("imminent_window_days", 7))
    return render_template(
        "schedule/lookahead.html",
        as_of=as_of,
        short_weeks=short_weeks,
        long_weeks=long_weeks,
        window=window,
        short=schedule_service.lookahead(rows, short_weeks, as_of),
        long=schedule_service.lookahead(rows, long_weeks, as_of),
        overdue=schedule_service.overdue_rows(rows, as_of),
        starting=schedule_service.starting_within(rows, window, as_of),
        finishing=schedule_service.finishing_within(rows, window, as_of),
        late_start=schedule_service.late_start_rows(rows, as_of),
        critical=schedule_service.critical_rows(rows),
        workfronts=schedule_service.critical_workfronts(rows),
        milestones=schedule_service.upcoming_milestones(rows, 15, as_of),
        overdue_milestones=schedule_service.overdue_milestones(rows, as_of),
    )


@bp.route("/recovery")
def recovery():
    as_of = request_date("as_of")
    return render_template(
        "schedule/recovery.html",
        as_of=as_of,
        comparisons=schedule_service.recovery_comparison(as_of),
        baseline=progress.baseline_version(),
    )


@bp.route("/versions", methods=["GET", "POST"])
def versions():
    if request.method == "POST":
        name = form_str("name", max_length=200)
        schedule_type = form_str("schedule_type", "CURRENT WORKING")
        if not name:
            flash(t("A schedule name is required."), "danger")
            return redirect(url_for("schedule.versions"))
        version = ScheduleVersion(
            name=name,
            revision=form_str("revision", max_length=60),
            schedule_type=schedule_type,
            issue_date=form_date("issue_date"),
            effective_date=form_date("effective_date"),
            status=form_str("status", "ACTIVE"),
            source_document_id=form_int("source_document_id"),
            notes=form_str("notes"),
        )
        _apply_version_flags(version, schedule_type)
        db.session.add(version)
        db.session.commit()
        flash(t("Schedule version '{label}' created. Import its activities from Data Import.", label=version.label), "success")
        return redirect(url_for("schedule.versions"))

    return render_template(
        "schedule/versions.html",
        versions=ScheduleVersion.query.order_by(ScheduleVersion.schedule_type,
                                                ScheduleVersion.effective_date).all(),
        documents=SourceDocument.query.order_by(SourceDocument.title).all(),
        activity_counts={
            v.id: WbsActivity.query.filter_by(schedule_version_id=v.id).count()
            for v in ScheduleVersion.query.all()
        },
    )


def _apply_version_flags(version, schedule_type):
    """Only one baseline and one current working version at a time.

    A new baseline is created unlocked so its activities can be imported. It
    locks itself the moment that import commits (see routes/dataio.py), which
    is the point from which it must stay immutable.
    """
    if schedule_type == "CONTRACTUAL BASELINE":
        for other in ScheduleVersion.query.filter_by(is_contractual_baseline=True).all():
            other.is_contractual_baseline = False
        version.is_contractual_baseline = True
    elif schedule_type in {"CURRENT WORKING", "APPROVED UPDATE"}:
        for other in ScheduleVersion.query.filter_by(is_current_working=True).all():
            other.is_current_working = False
            if other.status == "ACTIVE" and other.id != version.id:
                other.status = "SUPERSEDED"
        version.is_current_working = True


@bp.route("/versions/<int:version_id>/update", methods=["POST"])
def update_version(version_id):
    version = ScheduleVersion.query.get_or_404(version_id)
    action = form_str("action")

    if action == "lock":
        version.locked = True
        flash(t("'{label}' locked. Its activities can no longer be re-imported or edited.", label=version.label), "success")
    elif action == "unlock":
        if version.is_contractual_baseline:
            # Unlocking the contractual baseline is deliberately awkward: it is
            # allowed, so a mis-imported baseline can be corrected, but only on
            # an explicit typed confirmation, and it is recorded on the version.
            if form_str("confirm") != "UNLOCK BASELINE":
                flash(t("To unlock the contractual baseline, type UNLOCK BASELINE in the confirmation box. Contractual dates must not be changed casually."),
                      "danger")
            else:
                version.locked = False
                version.notes = ((version.notes or "") +
                                 f"\nContractual baseline unlocked on "
                                 f"{date.today():%d/%m/%Y}.").strip()
                flash(t("'{label}' unlocked. It will lock itself again after the next import. Every change to contractual dates from here is recorded.", label=version.label),
                      "warning")
        else:
            version.locked = False
            flash(t("'{label}' unlocked.", label=version.label), "warning")
    elif action == "set_current":
        if version.is_contractual_baseline:
            flash(t("The contractual baseline cannot also be the current working programme. Register the updated programme as a separate version."), "danger")
        else:
            _apply_version_flags(version, "CURRENT WORKING")
            flash(t("'{label}' is now the current working programme. The contractual baseline is unchanged.", label=version.label), "success")
    elif action == "archive":
        if version.is_contractual_baseline:
            flash(t("The contractual baseline cannot be archived."), "danger")
        else:
            version.status = "ARCHIVED"
            version.is_current_working = False
            flash(t("'{label}' archived.", label=version.label), "success")
    elif action == "edit":
        version.name = form_str("name", version.name, 200)
        version.revision = form_str("revision", version.revision, 60)
        version.issue_date = form_date("issue_date", version.issue_date)
        version.effective_date = form_date("effective_date", version.effective_date)
        version.notes = form_str("notes", version.notes)
        version.source_document_id = form_int("source_document_id", version.source_document_id)
        flash(t("Schedule version updated."), "success")
    db.session.commit()
    return redirect(url_for("schedule.versions"))


@bp.route("/versions/<int:version_id>/delete", methods=["POST"])
def delete_version(version_id):
    version = ScheduleVersion.query.get_or_404(version_id)
    if version.is_contractual_baseline:
        flash(t("The contractual baseline can never be deleted."), "danger")
        return redirect(url_for("schedule.versions"))
    if version.locked:
        flash(t("Unlock the version before deleting it."), "danger")
        return redirect(url_for("schedule.versions"))
    label = version.label
    db.session.delete(version)
    db.session.commit()
    flash(t("Schedule version '{label}' and its activities deleted.", label=label), "warning")
    return redirect(url_for("schedule.versions"))


@bp.route("/activity/<int:activity_id>", methods=["GET", "POST"])
def activity(activity_id):
    row = WbsActivity.query.get_or_404(activity_id)
    version = row.schedule_version

    if request.method == "POST":
        if version.locked and version.is_contractual_baseline:
            flash(t("Contractual baseline activities are read-only. Record execution data against the current working programme instead."), "danger")
            return redirect(url_for("schedule.activity", activity_id=activity_id))
        row.activity_name = form_str("activity_name", row.activity_name, 400)
        row.work_package = form_str("work_package", row.work_package, 200)
        row.discipline = form_str("discipline", row.discipline, 60)
        row.plan_start = form_date("plan_start", row.plan_start)
        row.plan_finish = form_date("plan_finish", row.plan_finish)
        row.actual_start = form_date("actual_start", row.actual_start)
        row.actual_finish = form_date("actual_finish", row.actual_finish)
        row.responsible_party = form_str("responsible_party", row.responsible_party, 160)
        row.status = form_str("status", row.status, 30)
        row.is_milestone = form_bool("is_milestone")
        row.unit = form_str("unit", row.unit, 30)
        row.total_required_quantity = form_float("total_required_quantity",
                                                 row.total_required_quantity)
        row.progress_method = form_str("progress_method", row.progress_method, 20)
        weight = form_float("progress_weight")
        if weight is not None:
            row.progress_weight = weight
            row.weight_basis = "APPROVED WEIGHT"
        reported = form_float("reported_completion_pct")
        if reported is not None:
            row.reported_completion_pct = max(0.0, min(reported, 100.0))
            row.manual_pct = True
        row.baseline_link_wbs = form_str("baseline_link_wbs", row.baseline_link_wbs, 60)
        row.notes = form_str("notes", row.notes)
        db.session.commit()
        flash(t("Activity {wbs_code} updated.", wbs_code=row.wbs_code), "success")
        return redirect(url_for("schedule.activity", activity_id=activity_id))

    as_of = request_date("as_of")
    baseline = progress.baseline_version()
    by_code, by_name = schedule_service.build_baseline_index(baseline)
    matched, match_kind = schedule_service.match_baseline(row, by_code, by_name)
    completed = progress.completed_quantity_by_wbs(as_of)
    actual_pct, actual_basis = progress.activity_actual_pct(row, completed)

    from app.models import DailyProgress
    daily_rows = (DailyProgress.query.filter_by(wbs_code=row.wbs_code)
                  .order_by(DailyProgress.entry_date.desc()).limit(30).all())

    return render_template(
        "schedule/activity.html",
        row=row, version=version, baseline=baseline, matched=matched,
        match_kind=match_kind, as_of=as_of, actual_pct=actual_pct,
        actual_basis=actual_basis, completed_quantity=completed.get(row.wbs_code, 0.0),
        daily_rows=daily_rows,
        baseline_codes=sorted(by_code.keys()),
    )


@bp.route("/export.csv")
def export():
    as_of = request_date("as_of")
    filename, text = exporters.export_schedule(as_of=as_of)
    return csv_response(filename, text)
