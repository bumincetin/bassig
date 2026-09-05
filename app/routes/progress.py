"""Progress measurement, rollup and production-rate forecasting."""
from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, url_for

from app.extensions import db
from app.i18n import translate as t
from app.models import ActivityQuantity, Area, WbsActivity
from app.routes._helpers import (
    arg_int,
    arg_str,
    csv_response,
    form_float,
    form_int,
    form_str,
    request_date,
)
from app.services import exporters, forecasting, progress as progress_service, settings

bp = Blueprint("progress", __name__, url_prefix="/progress")


@bp.route("/")
def index():
    as_of = request_date("as_of")
    version = progress_service.governing_version()
    rollup = progress_service.rollup(version, as_of)
    contractual = progress_service.contractual_planned_pct(as_of)
    completed = progress_service.completed_quantity_by_wbs(as_of)

    leaves = progress_service.activities_for(version, only_leaves=True) if version else []
    rows = []
    for activity in leaves:
        actual, basis = progress_service.activity_actual_pct(activity, completed)
        rows.append({
            "activity": activity,
            "actual": actual,
            "basis": basis,
            "weight": progress_service.activity_weight(activity),
            "completed_quantity": completed.get(activity.wbs_code, 0.0),
        })

    method = arg_str("method")
    if method:
        rows = [r for r in rows if (r["activity"].progress_method or "MANUAL").upper() == method]

    return render_template(
        "progress/index.html",
        as_of=as_of,
        version=version,
        rollup=rollup,
        contractual=contractual,
        rows=rows,
        method=method,
        area_progress=progress_service.progress_by_area(as_of),
        basis_report=progress_service.weighting_basis_report(),
        basis_options=["APPROVED WEIGHT", "DURATION DERIVED", "QUANTITY"],
    )


@bp.route("/basis", methods=["POST"])
def set_basis():
    basis = form_str("progress_weight_basis", "DURATION DERIVED")
    settings.set_value("progress_weight_basis", basis)
    db.session.commit()
    flash(t("Progress weighting basis set to {basis}. Rollups are recalculated immediately.", basis=basis),
          "success")
    return redirect(url_for("progress.index"))


@bp.route("/method/<int:activity_id>", methods=["POST"])
def set_method(activity_id):
    activity = WbsActivity.query.get_or_404(activity_id)
    activity.progress_method = form_str("progress_method", activity.progress_method, 20)
    total = form_float("total_required_quantity")
    if total is not None:
        activity.total_required_quantity = total
    unit = form_str("unit", max_length=30)
    if unit:
        activity.unit = unit
    weight = form_float("progress_weight")
    if weight is not None:
        activity.progress_weight = weight
        activity.weight_basis = "APPROVED WEIGHT"
    reported = form_float("reported_completion_pct")
    if reported is not None:
        activity.reported_completion_pct = max(0.0, min(reported, 100.0))
        activity.manual_pct = True
    db.session.commit()
    flash(t("Progress basis updated for {wbs_code}.", wbs_code=activity.wbs_code), "success")
    return redirect(request.referrer or url_for("progress.index"))


@bp.route("/quantities", methods=["GET", "POST"])
def quantities():
    if request.method == "POST":
        item = form_str("item", max_length=300)
        if not item:
            flash(t("An item description is required."), "danger")
            return redirect(url_for("progress.quantities"))
        row = ActivityQuantity(
            wbs_code=form_str("wbs_code", max_length=60),
            area_id=form_int("area_id"),
            activity_name=form_str("activity_name", max_length=300),
            item=item,
            total_quantity=form_float("total_quantity", 0.0),
            unit=form_str("unit", max_length=30),
            source_reference=form_str("source_reference", max_length=300),
            revision=form_str("revision", max_length=60),
            notes=form_str("notes"),
            source_document_id=form_int("source_document_id"),
        )
        db.session.add(row)
        db.session.commit()
        flash(t("Quantity register entry saved."), "success")
        return redirect(url_for("progress.quantities"))

    from app.models import SourceDocument
    return render_template(
        "progress/quantities.html",
        rows=ActivityQuantity.query.order_by(ActivityQuantity.wbs_code,
                                             ActivityQuantity.item).all(),
        areas=Area.query.filter_by(active=True).order_by(Area.area_code).all(),
        documents=SourceDocument.query.order_by(SourceDocument.title).all(),
    )


@bp.route("/quantities/<int:row_id>/delete", methods=["POST"])
def delete_quantity(row_id):
    row = ActivityQuantity.query.get_or_404(row_id)
    db.session.delete(row)
    db.session.commit()
    flash(t("Quantity register entry removed."), "warning")
    return redirect(url_for("progress.quantities"))


@bp.route("/forecast")
def forecast():
    as_of = request_date("as_of")
    window = arg_int("window") or int(settings.get("forecast_window_short_days", 7))
    rows = forecasting.forecast_table(as_of, window)
    return render_template(
        "progress/forecast.html",
        as_of=as_of,
        window=window,
        rows=rows,
        label=forecasting.LABEL,
        insufficient=forecasting.INSUFFICIENT,
        short_window=int(settings.get("forecast_window_short_days", 7)),
        long_window=int(settings.get("forecast_window_long_days", 14)),
    )


@bp.route("/export.csv")
def export():
    as_of = request_date("as_of")
    filename, text = exporters.export_schedule(as_of=as_of)
    return csv_response(filename, text)


@bp.route("/quantities/export.csv")
def export_quantities():
    filename, text = exporters.export_quantities()
    return csv_response(filename, text)
