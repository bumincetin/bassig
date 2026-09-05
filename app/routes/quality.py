"""Quality management: inspections, ITP points, checklists, NCRs, test records."""
from __future__ import annotations

from datetime import date

from flask import Blueprint, flash, redirect, render_template, request, url_for

from app import constants as C
from app.extensions import db
from app.i18n import translate as t
from app.models import Area, InspectionRequirement, QualityRecord, SourceDocument
from app.routes._helpers import (
    arg_date,
    arg_int,
    arg_str,
    csv_response,
    form_bool,
    form_date,
    form_int,
    form_str,
    request_date,
    save_photos,
)
from app.services import exporters, numbering, registers
from app.services.status_rules import quality_status

bp = Blueprint("quality", __name__, url_prefix="/quality")

#: Record types owned by this module. Punch List and NCR live in the Issues
#: module so they stay visibly separate from routine inspection records.
QUALITY_TYPES = ["INSPECTION", "ITP POINT", "CHECKLIST", "TEST RECORD", "CORRECTIVE ACTION"]


@bp.route("/")
def index():
    as_of = request_date("as_of")
    record_type = arg_str("type")
    status = arg_str("status")
    rows = registers.quality_query(
        record_type=record_type,
        status=status,
        area_id=arg_int("area"),
        wbs=arg_str("wbs"),
        date_from=arg_date("from"),
        date_to=arg_date("to"),
        overdue_only=arg_str("view") == "overdue",
    )
    if not record_type:
        rows = [r for r in rows if r.record_type in QUALITY_TYPES]
    return render_template(
        "quality/index.html",
        rows=rows,
        as_of=as_of,
        summary=registers.quality_summary(as_of),
        types=QUALITY_TYPES,
        areas=Area.query.filter_by(active=True).order_by(Area.area_code).all(),
        requirements=InspectionRequirement.query.filter_by(active=True)
                     .order_by(InspectionRequirement.itp_reference).all(),
        filters={"type": record_type, "status": status, "wbs": arg_str("wbs"),
                 "area": arg_int("area"), "view": arg_str("view"),
                 "from": arg_date("from"), "to": arg_date("to")},
        derived={r.id: quality_status(r, as_of) for r in rows},
        next_numbers={t: numbering.next_quality_number(t) for t in QUALITY_TYPES},
    )


@bp.route("/new", methods=["POST"])
def create():
    record_type = form_str("record_type", "INSPECTION")
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
        itp_reference=form_str("itp_reference", max_length=120),
        inspection_requirement_id=form_int("inspection_requirement_id"),
        title=form_str("title", max_length=300),
        description=form_str("description"),
        responsible_party=form_str("responsible_party", max_length=160),
        raised_by=form_str("raised_by", max_length=160),
        severity=form_str("severity", "MEDIUM", 20),
        target_closure_date=form_date("target_closure_date"),
        status=form_str("status", "OPEN"),
        inspection_result=form_str("inspection_result", max_length=30),
        evidence_reference=form_str("evidence_reference", max_length=300),
        comments=form_str("comments"),
    )
    db.session.add(record)
    db.session.flush()
    save_photos(request.files.getlist("photos"), caption=record.title,
                taken_date=record.record_date, quality_record_id=record.id)
    db.session.commit()
    flash(t("{title} {record_number} created.", title=record_type.title(), record_number=record.record_number), "success")
    return redirect(url_for("quality.detail", record_id=record.id))


@bp.route("/<int:record_id>", methods=["GET", "POST"])
def detail(record_id):
    record = QualityRecord.query.get_or_404(record_id)
    if request.method == "POST":
        record.record_date = form_date("record_date", record.record_date)
        record.wbs_code = form_str("wbs_code", record.wbs_code, 60)
        record.work_package = form_str("work_package", record.work_package, 200)
        record.area_id = form_int("area_id", record.area_id)
        record.discipline = form_str("discipline", record.discipline, 60)
        record.specification_reference = form_str("specification_reference",
                                                  record.specification_reference, 300)
        record.drawing_reference = form_str("drawing_reference", record.drawing_reference, 300)
        record.itp_reference = form_str("itp_reference", record.itp_reference, 120)
        record.title = form_str("title", record.title, 300)
        record.description = form_str("description", record.description)
        record.responsible_party = form_str("responsible_party", record.responsible_party, 160)
        record.severity = form_str("severity", record.severity, 20)
        record.target_closure_date = form_date("target_closure_date", record.target_closure_date)
        new_status = form_str("status", record.status)
        record.inspection_result = form_str("inspection_result", record.inspection_result, 30)
        record.corrective_action = form_str("corrective_action", record.corrective_action)
        record.evidence_reference = form_str("evidence_reference", record.evidence_reference, 300)
        record.comments = form_str("comments", record.comments)
        record.gate_code = form_str("gate_code", record.gate_code, 4)
        if new_status != record.status:
            record.status = new_status
            if new_status in C.QUALITY_CLOSED_STATES and not record.closure_date:
                record.closure_date = form_date("closure_date", date.today())
            elif new_status not in C.QUALITY_CLOSED_STATES:
                record.closure_date = None
        else:
            record.closure_date = form_date("closure_date", record.closure_date)
        save_photos(request.files.getlist("photos"), caption=record.title,
                    taken_date=record.record_date, quality_record_id=record.id)
        db.session.commit()
        flash(t("{record_number} updated.", record_number=record.record_number), "success")
        return redirect(url_for("quality.detail", record_id=record_id))

    as_of = request_date("as_of")
    return render_template(
        "quality/detail.html",
        record=record,
        derived=quality_status(record, as_of),
        as_of=as_of,
        areas=Area.query.filter_by(active=True).order_by(Area.area_code).all(),
        requirements=InspectionRequirement.query.filter_by(active=True).all(),
    )


@bp.route("/<int:record_id>/delete", methods=["POST"])
def delete(record_id):
    record = QualityRecord.query.get_or_404(record_id)
    number, record_type = record.record_number, record.record_type
    db.session.delete(record)
    db.session.commit()
    flash(t("{number} deleted.", number=number), "warning")
    if record_type in {"NCR", "PUNCH LIST"}:
        return redirect(url_for("issues.index"))
    return redirect(url_for("quality.index"))


# --------------------------------------------------------------------------
# ITP requirements
# --------------------------------------------------------------------------
@bp.route("/requirements", methods=["GET", "POST"])
def requirements():
    if request.method == "POST":
        reference = form_str("itp_reference", max_length=120)
        if not reference:
            flash(t("An ITP / checklist reference is required."), "danger")
            return redirect(url_for("quality.requirements"))
        db.session.add(InspectionRequirement(
            wbs_code=form_str("wbs_code", max_length=60),
            work_package=form_str("work_package", max_length=200),
            itp_reference=reference,
            inspection_type=form_str("inspection_type", max_length=80),
            point_type=form_str("point_type", "REVIEW", 20),
            required_evidence=form_str("required_evidence"),
            acceptance_criterion=form_str("acceptance_criterion"),
            applicable_specification=form_str("applicable_specification", max_length=300),
            discipline=form_str("discipline", max_length=60),
            source_document_id=form_int("source_document_id"),
            notes=form_str("notes"),
        ))
        db.session.commit()
        flash(t("Inspection requirement {reference} registered.", reference=reference), "success")
        return redirect(url_for("quality.requirements"))

    rows = InspectionRequirement.query.order_by(
        InspectionRequirement.wbs_code, InspectionRequirement.itp_reference).all()
    return render_template(
        "quality/requirements.html",
        rows=rows,
        documents=SourceDocument.query.order_by(SourceDocument.title).all(),
        hold_points=[r for r in rows if r.point_type == "HOLD"],
        witness_points=[r for r in rows if r.point_type == "WITNESS"],
    )


@bp.route("/requirements/<int:requirement_id>", methods=["POST"])
def update_requirement(requirement_id):
    row = InspectionRequirement.query.get_or_404(requirement_id)
    action = form_str("action")
    if action == "delete":
        db.session.delete(row)
        flash(t("Inspection requirement removed."), "warning")
    elif action == "toggle":
        row.active = not row.active
        flash(t("Requirement marked {inactive}.", inactive='active' if row.active else 'inactive'), "success")
    elif action == "raise":
        record = QualityRecord(
            record_number=numbering.next_quality_number("ITP POINT"),
            record_type="ITP POINT",
            record_date=date.today(),
            wbs_code=row.wbs_code,
            work_package=row.work_package,
            discipline=row.discipline,
            itp_reference=row.itp_reference,
            inspection_requirement_id=row.id,
            specification_reference=row.applicable_specification,
            title=f"{row.point_type} point: {row.inspection_type or row.itp_reference}",
            description=row.acceptance_criterion,
            severity="MEDIUM",
            status="OPEN",
        )
        db.session.add(record)
        db.session.commit()
        flash(t("{record_number} raised from {itp_reference}.", record_number=record.record_number, itp_reference=row.itp_reference), "success")
        return redirect(url_for("quality.detail", record_id=record.id))
    else:
        row.wbs_code = form_str("wbs_code", row.wbs_code, 60)
        row.work_package = form_str("work_package", row.work_package, 200)
        row.inspection_type = form_str("inspection_type", row.inspection_type, 80)
        row.point_type = form_str("point_type", row.point_type, 20)
        row.required_evidence = form_str("required_evidence", row.required_evidence)
        row.acceptance_criterion = form_str("acceptance_criterion", row.acceptance_criterion)
        row.applicable_specification = form_str("applicable_specification",
                                                row.applicable_specification, 300)
        row.discipline = form_str("discipline", row.discipline, 60)
        flash(t("Inspection requirement updated."), "success")
    db.session.commit()
    return redirect(url_for("quality.requirements"))


@bp.route("/export.csv")
def export():
    filename, text = exporters.export_quality(record_type=arg_str("type"))
    return csv_response(filename, text)


@bp.route("/requirements/export.csv")
def export_requirements():
    filename, text = exporters.export_inspection_requirements()
    return csv_response(filename, text)
