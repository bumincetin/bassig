"""Blockers and lost productivity."""
from __future__ import annotations

from datetime import date, timedelta

from flask import Blueprint, flash, redirect, render_template, request, url_for

from app import constants as C
from app.extensions import db
from app.i18n import translate as t
from app.models import Area, Blocker, DailySiteReport
from app.routes._helpers import (
    arg_date,
    arg_str,
    csv_response,
    form_date,
    form_datetime,
    form_float,
    form_int,
    form_str,
    request_date,
    save_photos,
)
from app.services import exporters, numbering, registers
from app.services.status_rules import action_status

bp = Blueprint("blockers", __name__, url_prefix="/blockers")


@bp.route("/")
def index():
    as_of = request_date("as_of")
    date_from = arg_date("from", date.today() - timedelta(days=90))
    date_to = arg_date("to", date.today())
    category = arg_str("category")
    status = arg_str("status")

    summary = registers.blocker_summary(date_from, date_to)
    rows = summary["rows"]
    if category:
        rows = [r for r in rows if r.category == category]
    if status:
        rows = [r for r in rows
                if action_status(r.status, None, None, as_of) == status
                or r.status == status]
    rows = sorted(rows, key=lambda r: (r.entry_date, r.id), reverse=True)

    return render_template(
        "blockers/index.html",
        as_of=as_of,
        rows=rows,
        summary=summary,
        date_from=date_from,
        date_to=date_to,
        category=category,
        status=status,
        areas=Area.query.filter_by(active=True).order_by(Area.area_code).all(),
        next_number=numbering.next_blocker_number(),
    )


@bp.route("/new", methods=["POST"])
def create():
    entry_date = form_date("entry_date", date.today())
    report = DailySiteReport.query.filter_by(report_date=entry_date).first()
    blocker = Blocker(
        blocker_number=numbering.next_blocker_number(),
        entry_date=entry_date,
        daily_report_id=report.id if report else None,
        wbs_code=form_str("wbs_code", max_length=60),
        area_id=form_int("area_id"),
        activity=form_str("activity", max_length=300),
        category=form_str("category", "Other", 40),
        description=form_str("description"),
        start_datetime=form_datetime("start_datetime"),
        end_datetime=form_datetime("end_datetime"),
        estimated_lost_hours=form_float("estimated_lost_hours", 0.0),
        actual_lost_hours=form_float("actual_lost_hours"),
        workers_affected=form_int("workers_affected", 0),
        equipment_affected=form_int("equipment_affected", 0),
        responsible_party=form_str("responsible_party", max_length=160),
        status="OPEN",
        action=form_str("action"),
        comments=form_str("comments"),
    )
    db.session.add(blocker)
    db.session.flush()
    save_photos(request.files.getlist("photos"), caption=blocker.description,
                taken_date=entry_date, blocker_id=blocker.id)
    db.session.commit()
    flash(t("Blocker {blocker_number} recorded.", blocker_number=blocker.blocker_number), "success")
    return redirect(url_for("blockers.detail", blocker_id=blocker.id))


@bp.route("/<int:blocker_id>", methods=["GET", "POST"])
def detail(blocker_id):
    blocker = Blocker.query.get_or_404(blocker_id)
    if request.method == "POST":
        blocker.entry_date = form_date("entry_date", blocker.entry_date)
        blocker.wbs_code = form_str("wbs_code", blocker.wbs_code, 60)
        blocker.area_id = form_int("area_id", blocker.area_id)
        blocker.activity = form_str("activity", blocker.activity, 300)
        blocker.category = form_str("category", blocker.category, 40)
        blocker.description = form_str("description", blocker.description)
        blocker.start_datetime = form_datetime("start_datetime", blocker.start_datetime)
        blocker.end_datetime = form_datetime("end_datetime", blocker.end_datetime)
        blocker.estimated_lost_hours = form_float("estimated_lost_hours",
                                                  blocker.estimated_lost_hours)
        blocker.actual_lost_hours = form_float("actual_lost_hours", blocker.actual_lost_hours)
        blocker.workers_affected = form_int("workers_affected", blocker.workers_affected)
        blocker.equipment_affected = form_int("equipment_affected", blocker.equipment_affected)
        blocker.responsible_party = form_str("responsible_party", blocker.responsible_party, 160)
        blocker.status = form_str("status", blocker.status)
        blocker.action = form_str("action", blocker.action)
        blocker.comments = form_str("comments", blocker.comments)
        save_photos(request.files.getlist("photos"), caption=blocker.description,
                    taken_date=blocker.entry_date, blocker_id=blocker.id)
        db.session.commit()
        flash(t("{blocker_number} updated.", blocker_number=blocker.blocker_number), "success")
        return redirect(url_for("blockers.detail", blocker_id=blocker_id))

    as_of = request_date("as_of")
    return render_template(
        "blockers/detail.html",
        blocker=blocker,
        derived=action_status(blocker.status, None, None, as_of),
        areas=Area.query.filter_by(active=True).order_by(Area.area_code).all(),
    )


@bp.route("/<int:blocker_id>/delete", methods=["POST"])
def delete(blocker_id):
    blocker = Blocker.query.get_or_404(blocker_id)
    number = blocker.blocker_number
    db.session.delete(blocker)
    db.session.commit()
    flash(t("{number} deleted.", number=number), "warning")
    return redirect(url_for("blockers.index"))


@bp.route("/analysis")
def analysis():
    date_from = arg_date("from", date.today() - timedelta(days=180))
    date_to = arg_date("to", date.today())
    return render_template("blockers/analysis.html",
                           summary=registers.blocker_summary(date_from, date_to),
                           date_from=date_from, date_to=date_to)


@bp.route("/export.csv")
def export():
    filename, text = exporters.export_blockers(date_from=arg_date("from"), date_to=arg_date("to"))
    return csv_response(filename, text)
