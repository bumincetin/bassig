"""Issues / actions register, plus the NCR and Punch List registers.

NCRs and Punch List items share the quality workflow engine but are kept
semantically separate: a punch item is never reported as an NCR, and a record
only becomes an NCR when a user classifies it as one.
"""
from __future__ import annotations

from datetime import date

from flask import Blueprint, flash, redirect, render_template, request, url_for

from app import constants as C
from app.extensions import db
from app.i18n import translate as t
from app.models import Area, Issue, QualityRecord
from app.routes._helpers import (
    arg_date,
    arg_str,
    csv_response,
    form_date,
    form_int,
    form_str,
    request_date,
    save_photos,
)
from app.services import exporters, numbering, registers
from app.services.status_rules import action_status, quality_status

bp = Blueprint("issues", __name__, url_prefix="/issues")


@bp.route("/")
def index():
    as_of = request_date("as_of")
    status = arg_str("status")
    category = arg_str("category")

    query = Issue.query
    if status:
        query = query.filter(Issue.status == status)
    if category:
        query = query.filter(Issue.category == category)
    rows = query.order_by(Issue.date_raised.desc(), Issue.id.desc()).all()

    ncrs = registers.quality_query(record_type="NCR")
    punch = registers.quality_query(record_type="PUNCH LIST")

    return render_template(
        "issues/index.html",
        as_of=as_of,
        rows=rows,
        derived={r.id: action_status(r.status, r.target_date, r.closed_date, as_of) for r in rows},
        summary=registers.issue_summary(as_of),
        ncrs=ncrs,
        punch=punch,
        ncr_derived={r.id: quality_status(r, as_of) for r in ncrs},
        punch_derived={r.id: quality_status(r, as_of) for r in punch},
        quality_summary=registers.quality_summary(as_of),
        areas=Area.query.filter_by(active=True).order_by(Area.area_code).all(),
        observations=registers.overdue_observations(as_of),
        filters={"status": status, "category": category},
        next_issue=numbering.next_issue_number(),
        next_ncr=numbering.next_quality_number("NCR"),
        next_punch=numbering.next_quality_number("PUNCH LIST"),
    )


# --------------------------------------------------------------------------
# Actions
# --------------------------------------------------------------------------
@bp.route("/new", methods=["POST"])
def create():
    title = form_str("title", max_length=300)
    if not title:
        flash(t("A title is required."), "danger")
        return redirect(url_for("issues.index"))
    issue = Issue(
        issue_number=numbering.next_issue_number(),
        date_raised=form_date("date_raised", date.today()),
        title=title,
        description=form_str("description"),
        category=form_str("category", "Other", 40),
        area_id=form_int("area_id"),
        wbs_code=form_str("wbs_code", max_length=60),
        priority=form_str("priority", "MEDIUM", 20),
        raised_by=form_str("raised_by", max_length=160),
        responsible_party=form_str("responsible_party", max_length=160),
        target_date=form_date("target_date"),
        status="OPEN",
        comments=form_str("comments"),
    )
    db.session.add(issue)
    db.session.commit()
    flash(t("Action {issue_number} raised.", issue_number=issue.issue_number), "success")
    return redirect(url_for("issues.detail", issue_id=issue.id))


@bp.route("/<int:issue_id>", methods=["GET", "POST"])
def detail(issue_id):
    issue = Issue.query.get_or_404(issue_id)
    if request.method == "POST":
        issue.title = form_str("title", issue.title, 300)
        issue.description = form_str("description", issue.description)
        issue.category = form_str("category", issue.category, 40)
        issue.area_id = form_int("area_id", issue.area_id)
        issue.wbs_code = form_str("wbs_code", issue.wbs_code, 60)
        issue.priority = form_str("priority", issue.priority, 20)
        issue.responsible_party = form_str("responsible_party", issue.responsible_party, 160)
        issue.target_date = form_date("target_date", issue.target_date)
        issue.action = form_str("action", issue.action)
        issue.comments = form_str("comments", issue.comments)
        new_status = form_str("status", issue.status)
        if new_status == "CLOSED" and issue.status != "CLOSED":
            issue.closed_date = form_date("closed_date", date.today())
        elif new_status != "CLOSED":
            issue.closed_date = None
        issue.status = new_status
        db.session.commit()
        flash(t("{issue_number} updated.", issue_number=issue.issue_number), "success")
        return redirect(url_for("issues.detail", issue_id=issue_id))

    as_of = request_date("as_of")
    return render_template(
        "issues/detail.html",
        issue=issue,
        derived=action_status(issue.status, issue.target_date, issue.closed_date, as_of),
        areas=Area.query.filter_by(active=True).order_by(Area.area_code).all(),
    )


@bp.route("/<int:issue_id>/delete", methods=["POST"])
def delete(issue_id):
    issue = Issue.query.get_or_404(issue_id)
    number = issue.issue_number
    db.session.delete(issue)
    db.session.commit()
    flash(t("{number} deleted.", number=number), "warning")
    return redirect(url_for("issues.index"))


# --------------------------------------------------------------------------
# NCR and Punch List
# --------------------------------------------------------------------------
def _create_quality(record_type, redirect_anchor):
    title = form_str("title", max_length=300)
    if not title:
        flash(t("A description is required for a new {record_type}.", record_type=record_type), "danger")
        return redirect(url_for("issues.index"))
    record = QualityRecord(
        record_number=numbering.next_quality_number(record_type),
        record_type=record_type,
        record_date=form_date("record_date", date.today()),
        wbs_code=form_str("wbs_code", max_length=60),
        work_package=form_str("work_package", max_length=200),
        area_id=form_int("area_id"),
        discipline=form_str("discipline", max_length=60),
        specification_reference=form_str("specification_reference", max_length=300),
        drawing_reference=form_str("drawing_reference", max_length=300),
        title=title,
        description=form_str("description"),
        responsible_party=form_str("responsible_party", max_length=160),
        raised_by=form_str("raised_by", max_length=160),
        severity=form_str("severity", "MEDIUM", 20),
        target_closure_date=form_date("target_closure_date"),
        status="OPEN",
        gate_code=form_str("gate_code", max_length=4),
        comments=form_str("comments"),
    )
    db.session.add(record)
    db.session.flush()
    save_photos(request.files.getlist("photos"), caption=title,
                taken_date=record.record_date, quality_record_id=record.id)
    db.session.commit()
    flash(t("{title} {record_number} raised.", title=record_type.title(), record_number=record.record_number), "success")
    return redirect(url_for("quality.detail", record_id=record.id))


@bp.route("/ncr/new", methods=["POST"])
def create_ncr():
    return _create_quality("NCR", "ncr")


@bp.route("/punch/new", methods=["POST"])
def create_punch():
    return _create_quality("PUNCH LIST", "punch")


@bp.route("/quality/<int:record_id>/reclassify", methods=["POST"])
def reclassify(record_id):
    """Explicit, user-driven conversion between NCR and Punch List."""
    record = QualityRecord.query.get_or_404(record_id)
    target = form_str("record_type")
    if target not in {"NCR", "PUNCH LIST"}:
        flash(t("Reclassification is only available between NCR and Punch List."), "danger")
        return redirect(url_for("quality.detail", record_id=record_id))
    if target == record.record_type:
        flash(t("The record already has that classification."), "warning")
        return redirect(url_for("quality.detail", record_id=record_id))
    old_number, old_type = record.record_number, record.record_type
    record.record_type = target
    record.record_number = numbering.next_quality_number(target)
    record.comments = ((record.comments or "") +
                       f"\nReclassified from {old_type} ({old_number}) to {target} "
                       f"on {date.today():%d/%m/%Y}.").strip()
    db.session.commit()
    flash(t("{old_number} reclassified as {target} and renumbered {record_number}.", old_number=old_number, target=target, record_number=record.record_number),
          "success")
    return redirect(url_for("quality.detail", record_id=record_id))


@bp.route("/export.csv")
def export():
    filename, text = exporters.export_issues()
    return csv_response(filename, text)


@bp.route("/ncr/export.csv")
def export_ncr():
    filename, text = exporters.export_quality(record_type="NCR")
    return csv_response(filename, text)


@bp.route("/punch/export.csv")
def export_punch():
    filename, text = exporters.export_quality(record_type="PUNCH LIST")
    return csv_response(filename, text)
