"""Daily Site Diary: header, progress lines, plant, observations, photographs."""
from __future__ import annotations

from datetime import date, timedelta

from flask import Blueprint, flash, redirect, render_template, request, url_for
from sqlalchemy import func

from app import constants as C
from app.extensions import db
from app.i18n import format_date, translate as t
from app.models import (
    Area,
    Blocker,
    Contractor,
    DailyProgress,
    DailySiteReport,
    Delivery,
    EquipmentEntry,
    Material,
    MaterialTransaction,
    SiteObservation,
    WorkforceEntry,
)
from app.routes._helpers import (
    arg_date,
    arg_int,
    csv_response,
    form_bool,
    form_date,
    form_float,
    form_int,
    form_str,
    request_date,
    save_photos,
)
from app.services import (
    exporters,
    numbering,
    procurement_service,
    progress,
    schedule_service,
)

bp = Blueprint("daily", __name__, url_prefix="/daily")


def _lookup_lists():
    from app.models import Project
    version = progress.governing_version()
    activities = progress.activities_for(version, only_leaves=True) if version else []
    project = Project.query.first()
    return {
        "areas": Area.query.filter_by(active=True).order_by(Area.area_code).all(),
        "contractors": Contractor.query.filter_by(active=True).order_by(Contractor.name).all(),
        "activities": activities,
        "version": version,
        "materials": Material.query.order_by(Material.item).all(),
        "wind_threshold": project.adverse_wind_ms if project else None,
        "rain_threshold": project.adverse_rain_mm_h if project else None,
    }


@bp.route("/")
def index():
    date_from = arg_date("from", date.today() - timedelta(days=30))
    date_to = arg_date("to", date.today())
    reports = (DailySiteReport.query
               .filter(DailySiteReport.report_date.between(date_from, date_to))
               .order_by(DailySiteReport.report_date.desc()).all())
    totals = {}
    for report in reports:
        row = db.session.query(
            func.coalesce(func.sum(DailyProgress.planned_quantity), 0.0),
            func.coalesce(func.sum(DailyProgress.actual_quantity), 0.0),
            func.count(DailyProgress.id),
        ).filter(DailyProgress.daily_report_id == report.id).one()
        totals[report.id] = {"planned": float(row[0] or 0), "actual": float(row[1] or 0),
                             "entries": int(row[2] or 0)}
    recorded = {r.report_date for r in reports}
    # Working days in the window with no diary at all, so a gap is visible
    # rather than something you have to notice yourself.
    missing, cursor = [], date_from
    while cursor <= min(date_to, date.today()):
        if cursor not in recorded and cursor.weekday() != 6:
            missing.append(cursor)
        cursor += timedelta(days=1)
    return render_template("daily/index.html", reports=reports, totals=totals,
                           date_from=date_from, date_to=date_to,
                           missing=missing[-14:], missing_total=len(missing),
                           next_number=numbering.next_daily_report_number())


def _open_or_create(report_date, prepared_by=None):
    """Return today's diary, creating it on first use.

    The site team should not have to decide whether a report already exists
    before they can record what happened.
    """
    report = DailySiteReport.query.filter_by(report_date=report_date).first()
    created = False
    if report is None:
        report = DailySiteReport(
            report_date=report_date,
            report_number=numbering.next_daily_report_number(),
            shift="DAY", prepared_by=prepared_by,
        )
        db.session.add(report)
        db.session.commit()
        created = True
    return report, created


@bp.route("/today")
def today():
    """One click from anywhere to the entry screen for a given day."""
    report_date = arg_date("date", date.today())
    # Work is recorded after it happens. A diary dated in the future would
    # carry quantities forward into days that have not been worked yet.
    if report_date > date.today():
        flash(t("A site diary cannot be opened for a future date. "
                "{report_date} was opened instead.",
                report_date=format_date(date.today())), "warning")
        report_date = date.today()
    report, created = _open_or_create(report_date)
    if created:
        flash(t("Started the site diary for {report_date} as {report_number}. Quantities carry forward from the previous days automatically.", report_date=format_date(report_date), report_number=report.report_number), "success")
    return redirect(url_for("daily.detail", report_id=report.id))


@bp.route("/new", methods=["GET", "POST"])
def create():
    if request.method == "POST":
        report_date = form_date("report_date", date.today())
        if report_date > date.today():
            flash(t("A site diary cannot be opened for a future date."), "danger")
            return redirect(url_for("daily.create"))
        existing = DailySiteReport.query.filter_by(report_date=report_date).first()
        if existing:
            flash(t("A daily report already exists for {report_date}. Open it to continue recording.", report_date=format_date(report_date)), "warning")
            return redirect(url_for("daily.detail", report_id=existing.id))
        report = DailySiteReport(
            report_date=report_date,
            report_number=form_str("report_number") or numbering.next_daily_report_number(),
            weather=form_str("weather", max_length=60),
            weather_pm=form_str("weather_pm", max_length=60),
            temperature_min_c=form_float("temperature_min_c"),
            temperature_max_c=form_float("temperature_max_c"),
            shift=form_str("shift", "DAY"),
            prepared_by=form_str("prepared_by", max_length=160),
            contractor_id=form_int("contractor_id"),
            subcontractors=form_str("subcontractors", max_length=400),
            work_start_time=form_str("work_start_time", max_length=10),
            work_end_time=form_str("work_end_time", max_length=10),
            max_wind_ms=form_float("max_wind_ms"),
            max_rain_mm_h=form_float("max_rain_mm_h"),
            adverse_weather_claimed=form_bool("adverse_weather_claimed"),
            general_comments=form_str("general_comments"),
            upcoming_work=form_str("upcoming_work"),
        )
        db.session.add(report)
        db.session.commit()
        flash(t("Daily site report {report_number} created for {report_date}.", report_number=report.report_number, report_date=format_date(report_date)), "success")
        return redirect(url_for("daily.detail", report_id=report.id))

    return render_template("daily/form.html", report=None,
                           next_number=numbering.next_daily_report_number(),
                           default_date=min(arg_date("date", date.today()), date.today()),
                           max_date=date.today(),
                           **_lookup_lists())


@bp.route("/<int:report_id>", methods=["GET", "POST"])
def detail(report_id):
    report = DailySiteReport.query.get_or_404(report_id)
    if request.method == "POST":
        report.report_number = form_str("report_number", report.report_number)
        report.weather = form_str("weather", report.weather, 60)
        report.weather_pm = form_str("weather_pm", report.weather_pm, 60)
        report.temperature_min_c = form_float("temperature_min_c", report.temperature_min_c)
        report.temperature_max_c = form_float("temperature_max_c", report.temperature_max_c)
        report.shift = form_str("shift", report.shift)
        report.prepared_by = form_str("prepared_by", report.prepared_by, 160)
        report.contractor_id = form_int("contractor_id", report.contractor_id)
        report.subcontractors = form_str("subcontractors", report.subcontractors, 400)
        report.work_start_time = form_str("work_start_time", report.work_start_time, 10)
        report.work_end_time = form_str("work_end_time", report.work_end_time, 10)
        report.max_wind_ms = form_float("max_wind_ms", report.max_wind_ms)
        report.max_rain_mm_h = form_float("max_rain_mm_h", report.max_rain_mm_h)
        report.adverse_weather_claimed = form_bool("adverse_weather_claimed")
        report.general_comments = form_str("general_comments", report.general_comments)
        report.upcoming_work = form_str("upcoming_work", report.upcoming_work)
        db.session.commit()
        flash(t("Daily report header saved."), "success")
        return redirect(url_for("daily.detail", report_id=report.id))

    lists = _lookup_lists()
    blockers = Blocker.query.filter_by(daily_report_id=report.id).all()
    movements = procurement_service.day_movements(report.report_date)
    material_views = {m.id: procurement_service.material_view(m, report.report_date)
                      for m in lists["materials"]}
    previous = (DailySiteReport.query
                .filter(DailySiteReport.report_date < report.report_date)
                .order_by(DailySiteReport.report_date.desc()).first())
    following = (DailySiteReport.query
                 .filter(DailySiteReport.report_date > report.report_date)
                 .order_by(DailySiteReport.report_date).first())
    return render_template(
        "daily/detail.html", report=report, blockers=blockers,
        deliveries=movements["deliveries"], movements=movements["movements"],
        material_views=material_views, previous=previous, following=following,
        **lists)


@bp.route("/<int:report_id>/delete", methods=["POST"])
def delete(report_id):
    report = DailySiteReport.query.get_or_404(report_id)
    label = report.report_number or str(report.report_date)
    db.session.delete(report)
    db.session.commit()
    flash(t("Daily report {label} and all its lines were deleted.", label=label), "warning")
    return redirect(url_for("daily.index"))


# --------------------------------------------------------------------------
# Progress lines
# --------------------------------------------------------------------------
@bp.route("/<int:report_id>/progress", methods=["POST"])
def add_progress(report_id):
    report = DailySiteReport.query.get_or_404(report_id)
    wbs_code = form_str("wbs_code", max_length=60)
    if not wbs_code:
        flash(t("Select the WBS activity for the progress line."), "danger")
        return redirect(url_for("daily.detail", report_id=report_id))

    version = progress.governing_version()
    activity = None
    if version:
        from app.models import WbsActivity
        activity = WbsActivity.query.filter_by(
            schedule_version_id=version.id, wbs_code=wbs_code).first()

    cumulative_before = form_float("cumulative_before")
    if cumulative_before is None:
        prior = db.session.query(
            func.coalesce(func.sum(DailyProgress.actual_quantity), 0.0)
        ).filter(DailyProgress.wbs_code == wbs_code,
                 DailyProgress.entry_date < report.report_date).scalar()
        cumulative_before = float(prior or 0.0)

    entry = DailyProgress(
        daily_report_id=report.id,
        entry_date=report.report_date,
        wbs_code=wbs_code,
        activity_name=form_str("activity_name",
                               activity.activity_name if activity else None, 400),
        work_package=form_str("work_package",
                              activity.work_package if activity else None, 200),
        area_id=form_int("area_id"),
        planned_quantity=form_float("planned_quantity", 0.0),
        actual_quantity=form_float("actual_quantity", 0.0),
        unit=form_str("unit", activity.unit if activity else None, 30),
        cumulative_before=cumulative_before,
        total_required_quantity=form_float(
            "total_required_quantity",
            activity.total_required_quantity if activity else None),
        workers=form_int("workers", 0),
        hours=form_float("hours", 0.0),
        comments=form_str("comments"),
        activity_affected=form_bool("activity_affected"),
        blocker_category=form_str("blocker_category", max_length=40),
        blocker_description=form_str("blocker_description"),
        estimated_lost_hours=form_float("estimated_lost_hours", 0.0),
    )
    db.session.add(entry)
    db.session.flush()
    # Entering a past day must not leave later days carrying a stale running
    # total, so the whole chain for this activity is rebased.
    rebased = progress.rebase_cumulatives(wbs_code)

    created_blocker = None
    if entry.activity_affected and entry.blocker_category:
        created_blocker = Blocker(
            blocker_number=numbering.next_blocker_number(),
            entry_date=report.report_date,
            daily_report_id=report.id,
            wbs_code=entry.wbs_code,
            area_id=entry.area_id,
            activity=entry.activity_name,
            category=entry.blocker_category,
            description=entry.blocker_description,
            estimated_lost_hours=entry.estimated_lost_hours or 0.0,
            workers_affected=entry.workers or 0,
            status="OPEN",
            comments="Raised automatically from the Daily Site Diary.",
        )
        db.session.add(created_blocker)

    db.session.commit()
    message = t("Progress line saved.")
    if created_blocker:
        message = t("Progress line saved and blocker {number} raised.",
                    number=created_blocker.blocker_number)
    if rebased:
        message += " " + t("{count} later cumulative total(s) were rebased because "
                           "this entry is out of date order.", count=rebased)
    flash(message, "success")
    return redirect(url_for("daily.detail", report_id=report_id))


@bp.route("/progress/<int:entry_id>/delete", methods=["POST"])
def delete_progress(entry_id):
    entry = DailyProgress.query.get_or_404(entry_id)
    report_id, wbs_code = entry.daily_report_id, entry.wbs_code
    db.session.delete(entry)
    db.session.flush()
    rebased = progress.rebase_cumulatives(wbs_code)
    db.session.commit()
    message = t("Progress line removed.")
    if rebased:
        message += " " + t("{count} later cumulative total(s) were rebased.",
                           count=rebased)
    flash(message, "warning")
    return redirect(url_for("daily.detail", report_id=report_id))


# --------------------------------------------------------------------------
# Workforce / equipment / observations
# --------------------------------------------------------------------------
@bp.route("/<int:report_id>/workforce", methods=["POST"])
def add_workforce(report_id):
    report = DailySiteReport.query.get_or_404(report_id)
    contractor_id = form_int("contractor_id")
    entry = WorkforceEntry(
        daily_report_id=report.id,
        entry_date=report.report_date,
        contractor_id=contractor_id,
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
    flash(t("Workforce line saved."), "success")
    return redirect(url_for("daily.detail", report_id=report_id))


@bp.route("/workforce/<int:entry_id>/delete", methods=["POST"])
def delete_workforce(entry_id):
    entry = WorkforceEntry.query.get_or_404(entry_id)
    report_id = entry.daily_report_id
    db.session.delete(entry)
    db.session.commit()
    flash(t("Workforce line removed."), "warning")
    return redirect(url_for("daily.detail", report_id=report_id))


@bp.route("/<int:report_id>/equipment", methods=["POST"])
def add_equipment(report_id):
    report = DailySiteReport.query.get_or_404(report_id)
    entry = EquipmentEntry(
        daily_report_id=report.id,
        entry_date=report.report_date,
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
    flash(t("Plant / equipment line saved."), "success")
    return redirect(url_for("daily.detail", report_id=report_id))


@bp.route("/equipment/<int:entry_id>/delete", methods=["POST"])
def delete_equipment(entry_id):
    entry = EquipmentEntry.query.get_or_404(entry_id)
    report_id = entry.daily_report_id
    db.session.delete(entry)
    db.session.commit()
    flash(t("Plant / equipment line removed."), "warning")
    return redirect(url_for("daily.detail", report_id=report_id))


@bp.route("/<int:report_id>/observation", methods=["POST"])
def add_observation(report_id):
    report = DailySiteReport.query.get_or_404(report_id)
    observation = SiteObservation(
        daily_report_id=report.id,
        entry_date=report.report_date,
        area_id=form_int("area_id"),
        wbs_code=form_str("wbs_code", max_length=60),
        observation=form_str("observation", "", ),
        category=form_str("category", "Other", 40),
        severity=form_str("severity", "LOW", 20),
        action_required=form_str("action_required"),
        responsible_party=form_str("responsible_party", max_length=160),
        target_date=form_date("target_date"),
        status="OPEN",
    )
    if not observation.observation:
        flash(t("An observation text is required."), "danger")
        return redirect(url_for("daily.detail", report_id=report_id))
    db.session.add(observation)
    db.session.flush()
    photos = save_photos(request.files.getlist("photos"),
                         caption=observation.observation[:200],
                         taken_date=report.report_date,
                         observation_id=observation.id,
                         daily_report_id=report.id)
    db.session.commit()
    flash(t("Observation saved with {count} photograph(s).", count=len(photos))
          if photos else t("Observation saved."), "success")
    return redirect(url_for("daily.detail", report_id=report_id))


@bp.route("/observation/<int:observation_id>/close", methods=["POST"])
def close_observation(observation_id):
    observation = SiteObservation.query.get_or_404(observation_id)
    observation.status = "CLOSED"
    observation.closed_date = date.today()
    db.session.commit()
    flash(t("Observation closed."), "success")
    return redirect(request.referrer or url_for("daily.index"))


@bp.route("/observation/<int:observation_id>/delete", methods=["POST"])
def delete_observation(observation_id):
    observation = SiteObservation.query.get_or_404(observation_id)
    report_id = observation.daily_report_id
    db.session.delete(observation)
    db.session.commit()
    flash(t("Observation removed."), "warning")
    return redirect(url_for("daily.detail", report_id=report_id))


# --------------------------------------------------------------------------
# Procurement recorded from the daily diary
# --------------------------------------------------------------------------
@bp.route("/<int:report_id>/delivery", methods=["POST"])
def add_delivery(report_id):
    """Record a delivery received on this day."""
    report = DailySiteReport.query.get_or_404(report_id)
    material_id = form_int("material_id")
    material = db.session.get(Material, material_id) if material_id else None
    if material is None:
        flash(t("Select the material line the delivery belongs to."), "danger")
        return redirect(url_for("daily.detail", report_id=report_id))

    quantity = form_float("quantity", 0.0)
    if not quantity:
        flash(t("Enter the quantity delivered."), "danger")
        return redirect(url_for("daily.detail", report_id=report_id))

    accepted = form_float("accepted_quantity", 0.0) or 0.0
    delivery = Delivery(
        material_id=material.id, package_id=material.package_id,
        delivery_date=report.report_date,
        delivery_note_reference=form_str("delivery_note_reference", max_length=200),
        quantity=quantity, unit=form_str("unit", material.unit, 30),
        status=form_str("status", "DELIVERED"),
        accepted_quantity=accepted,
        rejected_quantity=form_float("rejected_quantity", 0.0),
        inspection_date=form_date("inspection_date"),
        inspected_by=form_str("inspected_by", max_length=160),
        certificate_reference=form_str("certificate_reference", max_length=200),
        area_id=form_int("area_id"),
        comments=form_str("comments"),
    )
    db.session.add(delivery)
    db.session.flush()
    procurement_service.apply_delivery_to_material(delivery)
    if accepted:
        db.session.add(MaterialTransaction(
            material_id=material.id, transaction_date=report.report_date,
            transaction_type="RECEIPT ACCEPTED", quantity=accepted,
            area_id=delivery.area_id, reference=delivery.delivery_note_reference,
            comments="Recorded from the site diary."))
    db.session.commit()
    flash(t("Delivery of {quantity} {unit} {item} recorded. Delivered, accepted and "
            "installed remain separate quantities.",
            quantity=f"{quantity:g}", unit=material.unit or "",
            item=material.item).replace("  ", " "), "success")
    return redirect(url_for("daily.detail", report_id=report_id))


@bp.route("/<int:report_id>/material", methods=["POST"])
def add_material_movement(report_id):
    """Record material issued from store or fixed in the works on this day."""
    report = DailySiteReport.query.get_or_404(report_id)
    material_id = form_int("material_id")
    material = db.session.get(Material, material_id) if material_id else None
    if material is None:
        flash(t("Select the material line."), "danger")
        return redirect(url_for("daily.detail", report_id=report_id))

    quantity = form_float("quantity", 0.0)
    if not quantity:
        flash(t("Enter the quantity."), "danger")
        return redirect(url_for("daily.detail", report_id=report_id))

    movement_type = form_str("transaction_type", "ISSUE TO WORKFRONT")
    area_id = form_int("area_id")
    reference = form_str("reference", max_length=200)
    comments = form_str("comments")

    if movement_type in C.MATERIAL_TXN_INSTALL:
        procurement_service.record_installation(
            material, quantity, report.report_date, area_id, reference,
            comments or "Recorded from the site diary.")
        message = t("{quantity} {unit} of {item} recorded as installed. Cumulative "
                    "installed is now {total}.",
                    quantity=f"{quantity:g}", unit=material.unit or "",
                    item=material.item,
                    total=f"{material.installed:g}").replace("  ", " ")
    else:
        db.session.add(MaterialTransaction(
            material_id=material.id, transaction_date=report.report_date,
            transaction_type=movement_type, quantity=quantity, area_id=area_id,
            reference=reference, comments=comments or "Recorded from the site diary."))
        db.session.flush()
        message = t("{movement} of {quantity} {unit} {item} recorded. Available "
                    "stock is now {stock}.",
                    movement=movement_type.title(), quantity=f"{quantity:g}",
                    unit=material.unit or "", item=material.item,
                    stock=f"{procurement_service.stock_for(material):g}"
                    ).replace("  ", " ")
    db.session.commit()
    flash(message, "success")
    return redirect(url_for("daily.detail", report_id=report_id))


@bp.route("/movements/<int:txn_id>/delete", methods=["POST"])
def delete_movement(txn_id):
    row = MaterialTransaction.query.get_or_404(txn_id)
    material, report_date = row.material, row.transaction_date
    db.session.delete(row)
    db.session.flush()
    if material:
        procurement_service.recalculate_installed(material)
    db.session.commit()
    report = DailySiteReport.query.filter_by(report_date=report_date).first()
    flash(t("Stock movement removed."), "warning")
    if report:
        return redirect(url_for("daily.detail", report_id=report.id))
    return redirect(url_for("daily.index"))


@bp.route("/deliveries/<int:delivery_id>/delete", methods=["POST"])
def delete_delivery(delivery_id):
    row = Delivery.query.get_or_404(delivery_id)
    material, report_date = row.material, row.delivery_date
    db.session.delete(row)
    db.session.flush()
    if material:
        procurement_service.recalculate_material(material)
    db.session.commit()
    report = DailySiteReport.query.filter_by(report_date=report_date).first()
    flash(t("Delivery removed and the material totals recalculated."), "warning")
    if report:
        return redirect(url_for("daily.detail", report_id=report.id))
    return redirect(url_for("daily.index"))


@bp.route("/<int:report_id>/photos", methods=["POST"])
def add_photos(report_id):
    report = DailySiteReport.query.get_or_404(report_id)
    photos = save_photos(request.files.getlist("photos"),
                         caption=form_str("caption", max_length=400),
                         taken_date=report.report_date,
                         daily_report_id=report.id)
    db.session.commit()
    if photos:
        flash(t("{photos} photograph(s) attached.", photos=len(photos)), "success")
    else:
        flash(t("No supported image files were uploaded."), "warning")
    return redirect(url_for("daily.detail", report_id=report_id))


@bp.route("/observations")
def observations():
    date_from = arg_date("from", date.today() - timedelta(days=60))
    date_to = arg_date("to", date.today())
    category = request.args.get("category") or None
    query = SiteObservation.query.filter(
        SiteObservation.entry_date.between(date_from, date_to))
    if category:
        query = query.filter(SiteObservation.category == category)
    rows = query.order_by(SiteObservation.entry_date.desc()).all()
    return render_template("daily/observations.html", rows=rows, date_from=date_from,
                           date_to=date_to, category=category)


@bp.route("/export.csv")
def export():
    date_from = arg_date("from")
    date_to = arg_date("to")
    filename, text = exporters.export_daily_progress(date_from=date_from, date_to=date_to)
    return csv_response(filename, text)
