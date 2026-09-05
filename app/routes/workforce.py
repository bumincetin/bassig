"""Workforce and plant / equipment registers."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from flask import Blueprint, flash, redirect, render_template, request, url_for

from app import constants as C
from app.extensions import db
from app.i18n import translate as t
from app.models import Area, Contractor, DailySiteReport, EquipmentEntry, WorkforceEntry
from app.routes._helpers import (
    arg_date,
    arg_str,
    csv_response,
    form_bool,
    form_date,
    form_float,
    form_int,
    form_str,
)
from app.services import dashboard, exporters
from app.services.calculations import pct

bp = Blueprint("workforce", __name__, url_prefix="/workforce")


def _report_for(entry_date):
    return DailySiteReport.query.filter_by(report_date=entry_date).first()


@bp.route("/")
def index():
    date_from = arg_date("from", date.today() - timedelta(days=30))
    date_to = arg_date("to", date.today())

    workforce = (WorkforceEntry.query
                 .filter(WorkforceEntry.entry_date.between(date_from, date_to))
                 .order_by(WorkforceEntry.entry_date.desc()).all())
    equipment = (EquipmentEntry.query
                 .filter(EquipmentEntry.entry_date.between(date_from, date_to))
                 .order_by(EquipmentEntry.entry_date.desc()).all())

    by_discipline = defaultdict(lambda: {"workers": 0, "man_hours": 0.0, "days": set()})
    by_contractor = defaultdict(lambda: {"workers": 0, "man_hours": 0.0, "days": set()})
    for row in workforce:
        bucket = by_discipline[row.discipline or "Other"]
        bucket["workers"] += row.workers or 0
        bucket["man_hours"] += row.man_hours
        bucket["days"].add(row.entry_date)
        name = row.contractor.name if row.contractor else (row.contractor_name or "Unspecified")
        cbucket = by_contractor[name]
        cbucket["workers"] += row.workers or 0
        cbucket["man_hours"] += row.man_hours
        cbucket["days"].add(row.entry_date)

    equipment_totals = {
        "working": sum(e.working_hours or 0.0 for e in equipment),
        "idle": sum(e.idle_hours or 0.0 for e in equipment),
        "breakdown": sum(e.breakdown_hours or 0.0 for e in equipment),
    }
    equipment_totals["total"] = sum(equipment_totals.values())
    equipment_totals["utilisation"] = pct(equipment_totals["working"], equipment_totals["total"])
    equipment_totals["lost"] = equipment_totals["idle"] + equipment_totals["breakdown"]

    by_equipment = defaultdict(lambda: {"units": 0, "working": 0.0, "idle": 0.0,
                                        "breakdown": 0.0})
    for row in equipment:
        bucket = by_equipment[row.equipment_type or "Unspecified"]
        bucket["units"] += row.quantity or 0
        bucket["working"] += row.working_hours or 0.0
        bucket["idle"] += row.idle_hours or 0.0
        bucket["breakdown"] += row.breakdown_hours or 0.0
    for bucket in by_equipment.values():
        total = bucket["working"] + bucket["idle"] + bucket["breakdown"]
        bucket["utilisation"] = pct(bucket["working"], total)

    days = (date_to - date_from).days + 1
    return render_template(
        "workforce/index.html",
        date_from=date_from, date_to=date_to,
        workforce=workforce, equipment=equipment,
        by_discipline={k: {**v, "days": len(v["days"])} for k, v in sorted(by_discipline.items())},
        by_contractor={k: {**v, "days": len(v["days"])} for k, v in sorted(by_contractor.items())},
        by_equipment=dict(sorted(by_equipment.items())),
        equipment_totals=equipment_totals,
        total_workers=sum(r.workers or 0 for r in workforce),
        total_man_hours=sum(r.man_hours for r in workforce),
        trend=dashboard.workforce_trend(days, date_to),
        utilisation_trend=dashboard.equipment_utilisation_trend(days, date_to),
        areas=Area.query.filter_by(active=True).order_by(Area.area_code).all(),
        contractors=Contractor.query.filter_by(active=True).order_by(Contractor.name).all(),
    )


@bp.route("/workforce", methods=["POST"])
def add_workforce():
    entry_date = form_date("entry_date", date.today())
    report = _report_for(entry_date)
    entry = WorkforceEntry(
        daily_report_id=report.id if report else None,
        entry_date=entry_date,
        contractor_id=form_int("contractor_id"),
        contractor_name=form_str("contractor_name", max_length=200),
        discipline=form_str("discipline", "Other", 60),
        work_package=form_str("work_package", max_length=200),
        area_id=form_int("area_id"),
        workers=form_int("workers", 0),
        hours=form_float("hours", 0.0),
        overtime_hours=form_float("overtime_hours", 0.0),
        comments=form_str("comments"),
    )
    db.session.add(entry)
    db.session.commit()
    flash(t("Workforce entry recorded."), "success")
    return redirect(request.referrer or url_for("workforce.index"))


@bp.route("/equipment", methods=["POST"])
def add_equipment():
    entry_date = form_date("entry_date", date.today())
    report = _report_for(entry_date)
    entry = EquipmentEntry(
        daily_report_id=report.id if report else None,
        entry_date=entry_date,
        equipment_type=form_str("equipment_type", "Unspecified", 160),
        contractor_id=form_int("contractor_id"),
        owner=form_str("owner", max_length=200),
        area_id=form_int("area_id"),
        quantity=form_int("quantity", 1),
        status=form_str("status", "WORKING"),
        working_hours=form_float("working_hours", 0.0),
        idle_hours=form_float("idle_hours", 0.0),
        breakdown_hours=form_float("breakdown_hours", 0.0),
        reason=form_str("reason", max_length=300),
        comments=form_str("comments"),
    )
    db.session.add(entry)
    db.session.commit()
    flash(t("Plant / equipment entry recorded."), "success")
    return redirect(request.referrer or url_for("workforce.index"))


@bp.route("/workforce/<int:entry_id>/delete", methods=["POST"])
def delete_workforce(entry_id):
    entry = WorkforceEntry.query.get_or_404(entry_id)
    db.session.delete(entry)
    db.session.commit()
    flash(t("Workforce entry removed."), "warning")
    return redirect(request.referrer or url_for("workforce.index"))


@bp.route("/equipment/<int:entry_id>/delete", methods=["POST"])
def delete_equipment(entry_id):
    entry = EquipmentEntry.query.get_or_404(entry_id)
    db.session.delete(entry)
    db.session.commit()
    flash(t("Plant / equipment entry removed."), "warning")
    return redirect(request.referrer or url_for("workforce.index"))


@bp.route("/contractors", methods=["GET", "POST"])
def contractors():
    if request.method == "POST":
        name = form_str("name", max_length=200)
        if not name:
            flash(t("A contractor name is required."), "danger")
            return redirect(url_for("workforce.contractors"))
        if Contractor.query.filter_by(name=name).first():
            flash(t("'{name}' is already registered.", name=name), "warning")
            return redirect(url_for("workforce.contractors"))
        db.session.add(Contractor(
            name=name,
            short_name=form_str("short_name", max_length=60),
            role=form_str("role", "SUBCONTRACTOR"),
            discipline=form_str("discipline", max_length=60),
            contact=form_str("contact", max_length=200),
            active=True,
            notes=form_str("notes"),
        ))
        db.session.commit()
        flash(t("Contractor '{name}' registered.", name=name), "success")
        return redirect(url_for("workforce.contractors"))

    return render_template("workforce/contractors.html",
                           rows=Contractor.query.order_by(Contractor.name).all())


@bp.route("/contractors/<int:contractor_id>", methods=["POST"])
def update_contractor(contractor_id):
    row = Contractor.query.get_or_404(contractor_id)
    action = form_str("action")
    if action == "toggle":
        row.active = not row.active
        flash(t("'{name}' marked {inactive}.", name=row.name, inactive='active' if row.active else 'inactive'), "success")
    elif action == "delete":
        db.session.delete(row)
        flash(t("'{name}' removed.", name=row.name), "warning")
    else:
        row.name = form_str("name", row.name, 200)
        row.short_name = form_str("short_name", row.short_name, 60)
        row.role = form_str("role", row.role)
        row.discipline = form_str("discipline", row.discipline, 60)
        row.contact = form_str("contact", row.contact, 200)
        row.notes = form_str("notes", row.notes)
        flash(t("Contractor updated."), "success")
    db.session.commit()
    return redirect(url_for("workforce.contractors"))


@bp.route("/export/workforce.csv")
def export_workforce():
    filename, text = exporters.export_workforce(date_from=arg_date("from"), date_to=arg_date("to"))
    return csv_response(filename, text)


@bp.route("/export/equipment.csv")
def export_equipment():
    filename, text = exporters.export_equipment(date_from=arg_date("from"), date_to=arg_date("to"))
    return csv_response(filename, text)
