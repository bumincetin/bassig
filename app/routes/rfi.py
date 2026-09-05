"""RFI / technical query register."""
from __future__ import annotations

from datetime import date

from flask import Blueprint, flash, redirect, render_template, request, url_for

from app import constants as C
from app.extensions import db
from app.i18n import translate as t
from app.models import Area, Blocker, Rfi
from app.routes._helpers import (
    arg_str,
    csv_response,
    form_bool,
    form_date,
    form_float,
    form_int,
    form_str,
    request_date,
    save_photos,
)
from app.services import exporters, numbering, registers
from app.services.status_rules import rfi_status

bp = Blueprint("rfi", __name__, url_prefix="/rfi")


@bp.route("/")
def index():
    as_of = request_date("as_of")
    status = arg_str("status")
    discipline = arg_str("discipline")

    rows = Rfi.query.order_by(Rfi.date_raised.desc(), Rfi.id.desc()).all()
    derived = {r.id: rfi_status(r, as_of) for r in rows}
    if status:
        rows = [r for r in rows if derived[r.id] == status]
    if discipline:
        rows = [r for r in rows if r.discipline == discipline]

    return render_template(
        "rfi/index.html",
        as_of=as_of,
        rows=rows,
        derived=derived,
        summary=registers.rfi_summary(as_of),
        areas=Area.query.filter_by(active=True).order_by(Area.area_code).all(),
        blockers=Blocker.query.order_by(Blocker.entry_date.desc()).limit(100).all(),
        filters={"status": status, "discipline": discipline},
        next_number=numbering.next_rfi_number(),
    )


@bp.route("/new", methods=["POST"])
def create():
    subject = form_str("subject", max_length=300)
    if not subject:
        flash(t("A subject is required to raise an RFI."), "danger")
        return redirect(url_for("rfi.index"))
    row = Rfi(
        rfi_number=numbering.next_rfi_number(),
        date_raised=form_date("date_raised", date.today()),
        raised_by=form_str("raised_by", max_length=160),
        area_id=form_int("area_id"),
        wbs_code=form_str("wbs_code", max_length=60),
        discipline=form_str("discipline", max_length=60),
        subject=subject,
        question=form_str("question"),
        reference=form_str("reference", max_length=300),
        responsible_party=form_str("responsible_party", max_length=160),
        required_response_date=form_date("required_response_date"),
        status="OPEN",
        schedule_impact=form_bool("schedule_impact"),
        estimated_delay_days=form_float("estimated_delay_days"),
        blocker_id=form_int("blocker_id"),
        comments=form_str("comments"),
    )
    db.session.add(row)
    db.session.flush()
    save_photos(request.files.getlist("photos"), caption=subject,
                taken_date=row.date_raised, rfi_id=row.id)
    db.session.commit()
    flash(t("RFI {rfi_number} raised.", rfi_number=row.rfi_number), "success")
    return redirect(url_for("rfi.detail", rfi_id=row.id))


@bp.route("/<int:rfi_id>", methods=["GET", "POST"])
def detail(rfi_id):
    row = Rfi.query.get_or_404(rfi_id)
    if request.method == "POST":
        row.date_raised = form_date("date_raised", row.date_raised)
        row.raised_by = form_str("raised_by", row.raised_by, 160)
        row.area_id = form_int("area_id", row.area_id)
        row.wbs_code = form_str("wbs_code", row.wbs_code, 60)
        row.discipline = form_str("discipline", row.discipline, 60)
        row.subject = form_str("subject", row.subject, 300)
        row.question = form_str("question", row.question)
        row.reference = form_str("reference", row.reference, 300)
        row.responsible_party = form_str("responsible_party", row.responsible_party, 160)
        row.required_response_date = form_date("required_response_date",
                                               row.required_response_date)
        row.response = form_str("response", row.response)
        row.schedule_impact = form_bool("schedule_impact")
        row.estimated_delay_days = form_float("estimated_delay_days", row.estimated_delay_days)
        row.blocker_id = form_int("blocker_id", row.blocker_id)
        row.comments = form_str("comments", row.comments)
        new_status = form_str("status", row.status)
        if new_status in {"ANSWERED", "CLOSED"} and not row.response_date:
            row.response_date = form_date("response_date", date.today())
        elif new_status == "OPEN":
            row.response_date = form_date("response_date", row.response_date)
        else:
            row.response_date = form_date("response_date", row.response_date)
        row.status = new_status
        save_photos(request.files.getlist("photos"), caption=row.subject,
                    taken_date=row.date_raised, rfi_id=row.id)
        db.session.commit()
        flash(t("{rfi_number} updated.", rfi_number=row.rfi_number), "success")
        return redirect(url_for("rfi.detail", rfi_id=rfi_id))

    as_of = request_date("as_of")
    return render_template(
        "rfi/detail.html",
        row=row,
        derived=rfi_status(row, as_of),
        areas=Area.query.filter_by(active=True).order_by(Area.area_code).all(),
        blockers=Blocker.query.order_by(Blocker.entry_date.desc()).limit(100).all(),
    )


@bp.route("/<int:rfi_id>/delete", methods=["POST"])
def delete(rfi_id):
    row = Rfi.query.get_or_404(rfi_id)
    number = row.rfi_number
    db.session.delete(row)
    db.session.commit()
    flash(t("{number} deleted.", number=number), "warning")
    return redirect(url_for("rfi.index"))


@bp.route("/export.csv")
def export():
    filename, text = exporters.export_rfis()
    return csv_response(filename, text)
