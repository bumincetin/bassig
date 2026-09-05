"""Contractual payment milestones and delay-damages exposure."""
from __future__ import annotations

from datetime import date

from flask import Blueprint, flash, redirect, render_template, request, url_for

from app.extensions import db
from app.i18n import translate as t
from app.models import PaymentMilestone, SourceDocument
from app.routes._helpers import (
    csv_response,
    form_date,
    form_float,
    form_int,
    form_str,
    request_date,
)
from app.services import commercial_service, exporters

bp = Blueprint("commercial", __name__, url_prefix="/commercial")

NOTE = ("Payment percentages come from Schedule 10 and the Contract Price from the signed "
        "Contract. A milestone is never marked achieved because physical progress suggests "
        "it -- achievement, certification, invoicing and payment are recorded by a person.")


@bp.route("/")
def index():
    as_of = request_date("as_of")
    return render_template(
        "commercial/index.html",
        as_of=as_of,
        summary=commercial_service.summary(as_of),
        exposure=commercial_service.delay_damages_exposure(as_of),
        statuses=commercial_service.PAYMENT_STATUS,
        gates=commercial_service.gate_link_options(),
        documents=SourceDocument.query.order_by(SourceDocument.title).all(),
        note=NOTE,
    )


@bp.route("/new", methods=["POST"])
def create():
    description = form_str("description", max_length=400)
    if not description:
        flash(t("A milestone description is required."), "danger")
        return redirect(url_for("commercial.index"))
    code = form_str("milestone_code", max_length=40)
    if code and PaymentMilestone.query.filter_by(milestone_code=code).first():
        flash(t("Payment milestone '{code}' already exists.", code=code), "warning")
        return redirect(url_for("commercial.index"))
    db.session.add(PaymentMilestone(
        sequence=form_int("sequence", PaymentMilestone.query.count() + 1),
        milestone_code=code,
        description=description,
        percentage=form_float("percentage", 0.0),
        wbs_code=form_str("wbs_code", max_length=60),
        gate_code=form_str("gate_code", max_length=4),
        package_code=form_str("package_code", max_length=40),
        planned_date=form_date("planned_date"),
        forecast_date=form_date("forecast_date"),
        status=form_str("status", "NOT STARTED"),
        source_document_id=form_int("source_document_id"),
        comments=form_str("comments"),
    ))
    db.session.commit()
    flash(t("Payment milestone '{description}' registered.", description=description[:60]), "success")
    return redirect(url_for("commercial.index"))


@bp.route("/<int:milestone_id>", methods=["POST"])
def update(milestone_id):
    row = PaymentMilestone.query.get_or_404(milestone_id)
    if form_str("action") == "delete":
        db.session.delete(row)
        db.session.commit()
        flash(t("Payment milestone removed."), "warning")
        return redirect(url_for("commercial.index"))

    row.description = form_str("description", row.description, 400)
    row.milestone_code = form_str("milestone_code", row.milestone_code, 40)
    row.sequence = form_int("sequence", row.sequence)
    row.percentage = form_float("percentage", row.percentage)
    row.wbs_code = form_str("wbs_code", row.wbs_code, 60)
    row.gate_code = form_str("gate_code", row.gate_code, 4)
    row.package_code = form_str("package_code", row.package_code, 40)
    row.planned_date = form_date("planned_date", row.planned_date)
    row.forecast_date = form_date("forecast_date", row.forecast_date)
    row.achieved_date = form_date("achieved_date", row.achieved_date)
    row.certified_date = form_date("certified_date", row.certified_date)
    row.invoiced_date = form_date("invoiced_date", row.invoiced_date)
    row.paid_date = form_date("paid_date", row.paid_date)
    row.evidence_reference = form_str("evidence_reference", row.evidence_reference, 300)
    row.comments = form_str("comments", row.comments)

    new_status = form_str("status", row.status)
    if new_status != row.status:
        # Recording a state also stamps its date if the user left it blank, but
        # never invents a date for a state the user did not select.
        stamps = {"ACHIEVED": "achieved_date", "CERTIFIED": "certified_date",
                  "INVOICED": "invoiced_date", "PAID": "paid_date"}
        field = stamps.get(new_status)
        if field and getattr(row, field) is None:
            setattr(row, field, date.today())
        row.status = new_status
    db.session.commit()
    flash(t("Payment milestone updated."), "success")
    return redirect(url_for("commercial.index"))


@bp.route("/export.csv")
def export():
    filename, text = exporters.export_payments()
    return csv_response(filename, text)
