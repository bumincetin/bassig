"""Procurement packages, materials, deliveries and warehouse movements."""
from __future__ import annotations

from datetime import date

from flask import Blueprint, flash, redirect, render_template, request, url_for

from app import constants as C
from app.extensions import db
from app.i18n import translate as t
from app.models import (
    Area,
    Delivery,
    Material,
    MaterialTransaction,
    ProcurementPackage,
    SourceDocument,
)
from app.routes._helpers import (
    arg_date,
    arg_str,
    csv_response,
    form_bool,
    form_date,
    form_float,
    form_int,
    form_str,
    request_date,
)
from app.services import exporters, procurement_service

bp = Blueprint("procurement", __name__, url_prefix="/procurement")


@bp.route("/")
def index():
    as_of = request_date("as_of")
    views = procurement_service.all_package_views(as_of)
    status_filter = arg_str("status")
    stage_filter = arg_str("stage")
    if status_filter:
        views = [v for v in views if v["status"] == status_filter]
    if stage_filter:
        views = [v for v in views if v["package"].stage == stage_filter]
    return render_template(
        "procurement/index.html",
        as_of=as_of,
        views=views,
        warnings=procurement_service.procurement_warnings(as_of),
        stages=procurement_service.stage_distribution(),
        documents=SourceDocument.query.order_by(SourceDocument.title).all(),
        status_filter=status_filter,
        stage_filter=stage_filter,
    )


@bp.route("/packages", methods=["POST"])
def create_package():
    code = form_str("package_code", max_length=40)
    name = form_str("package_name", max_length=200)
    if not code or not name:
        flash(t("Package code and name are both required."), "danger")
        return redirect(url_for("procurement.index"))
    if ProcurementPackage.query.filter_by(package_code=code).first():
        flash(t("Package '{code}' already exists.", code=code), "warning")
        return redirect(url_for("procurement.index"))
    package = ProcurementPackage(
        package_code=code,
        package_name=name,
        category=form_str("category", max_length=80),
        equipment=form_str("equipment", max_length=300),
        approved_vendors=form_str("approved_vendors"),
        responsible_party=form_str("responsible_party", max_length=160),
        stage=form_str("stage", "REQUIRED"),
        wbs_code=form_str("wbs_code", max_length=60),
        po_reference=form_str("po_reference", max_length=160),
        planned_delivery=form_date("planned_delivery"),
        forecast_delivery=form_date("forecast_delivery"),
        fat_required=form_bool("fat_required"),
        source_document_id=form_int("source_document_id"),
        comments=form_str("comments"),
    )
    if package.fat_required:
        package.fat_status = "NOT STARTED"
    db.session.add(package)
    db.session.commit()
    flash(t("Procurement package {code} created.", code=code), "success")
    return redirect(url_for("procurement.package", package_id=package.id))


@bp.route("/packages/<int:package_id>", methods=["GET", "POST"])
def package(package_id):
    row = ProcurementPackage.query.get_or_404(package_id)
    if request.method == "POST":
        row.package_name = form_str("package_name", row.package_name, 200)
        row.category = form_str("category", row.category, 80)
        row.equipment = form_str("equipment", row.equipment, 300)
        row.approved_vendors = form_str("approved_vendors", row.approved_vendors)
        row.responsible_party = form_str("responsible_party", row.responsible_party, 160)
        row.stage = form_str("stage", row.stage)
        row.wbs_code = form_str("wbs_code", row.wbs_code, 60)
        row.po_reference = form_str("po_reference", row.po_reference, 160)
        row.planned_delivery = form_date("planned_delivery", row.planned_delivery)
        row.forecast_delivery = form_date("forecast_delivery", row.forecast_delivery)
        row.actual_delivery = form_date("actual_delivery", row.actual_delivery)
        row.fat_required = form_bool("fat_required")
        row.fat_status = form_str("fat_status", row.fat_status)
        row.fat_date = form_date("fat_date", row.fat_date)
        row.source_document_id = form_int("source_document_id", row.source_document_id)
        row.comments = form_str("comments", row.comments)
        db.session.commit()
        flash(t("Package {package_code} updated.", package_code=row.package_code), "success")
        return redirect(url_for("procurement.package", package_id=package_id))

    as_of = request_date("as_of")
    return render_template(
        "procurement/package.html",
        view=procurement_service.package_view(row, as_of),
        as_of=as_of,
        areas=Area.query.filter_by(active=True).order_by(Area.area_code).all(),
        documents=SourceDocument.query.order_by(SourceDocument.title).all(),
    )


@bp.route("/packages/<int:package_id>/delete", methods=["POST"])
def delete_package(package_id):
    row = ProcurementPackage.query.get_or_404(package_id)
    code = row.package_code
    db.session.delete(row)
    db.session.commit()
    flash(t("Package {code} and its material lines were deleted.", code=code), "warning")
    return redirect(url_for("procurement.index"))


# --------------------------------------------------------------------------
# Materials
# --------------------------------------------------------------------------
@bp.route("/packages/<int:package_id>/materials", methods=["POST"])
def add_material(package_id):
    package_row = ProcurementPackage.query.get_or_404(package_id)
    item = form_str("item", max_length=300)
    if not item:
        flash(t("A material / equipment description is required."), "danger")
        return redirect(url_for("procurement.package", package_id=package_id))
    material = Material(
        package_id=package_row.id,
        item=item,
        manufacturer=form_str("manufacturer", max_length=200),
        vendor=form_str("vendor", max_length=200),
        approved_vendor=form_bool("approved_vendor"),
        unit=form_str("unit", max_length=30),
        contract_quantity=form_float("contract_quantity"),
        total_required=form_float("total_required", 0.0),
        ordered=form_float("ordered", 0.0),
        manufactured=form_float("manufactured", 0.0),
        po_reference=form_str("po_reference", max_length=160),
        fat_required=form_bool("fat_required"),
        planned_delivery=form_date("planned_delivery"),
        forecast_delivery=form_date("forecast_delivery"),
        allocated_area_id=form_int("allocated_area_id"),
        comments=form_str("comments"),
    )
    if material.fat_required:
        material.fat_status = "NOT STARTED"
    db.session.add(material)
    db.session.commit()
    flash(t("Material line '{item}' added.", item=item), "success")
    return redirect(url_for("procurement.package", package_id=package_id))


@bp.route("/materials")
def materials():
    as_of = request_date("as_of")
    rows = Material.query.order_by(Material.package_id, Material.item).all()
    views = [procurement_service.material_view(m, as_of) for m in rows]
    stock_filter = arg_str("stock")
    if stock_filter:
        views = [v for v in views if v["stock_status"] == stock_filter]
    return render_template("procurement/materials.html", views=views, as_of=as_of,
                           stock_filter=stock_filter,
                           areas=Area.query.filter_by(active=True).all())


@bp.route("/materials/<int:material_id>", methods=["GET", "POST"])
def material(material_id):
    row = Material.query.get_or_404(material_id)
    if request.method == "POST":
        row.item = form_str("item", row.item, 300)
        row.manufacturer = form_str("manufacturer", row.manufacturer, 200)
        row.vendor = form_str("vendor", row.vendor, 200)
        row.approved_vendor = form_bool("approved_vendor")
        row.unit = form_str("unit", row.unit, 30)
        row.contract_quantity = form_float("contract_quantity", row.contract_quantity)
        row.total_required = form_float("total_required", row.total_required)
        row.ordered = form_float("ordered", row.ordered)
        row.manufactured = form_float("manufactured", row.manufactured)
        # Installed is a site fact and is edited explicitly here; delivered and
        # accepted are derived from delivery records only.
        row.installed = form_float("installed", row.installed)
        row.po_reference = form_str("po_reference", row.po_reference, 160)
        row.fat_required = form_bool("fat_required")
        row.fat_status = form_str("fat_status", row.fat_status)
        row.fat_date = form_date("fat_date", row.fat_date)
        row.planned_delivery = form_date("planned_delivery", row.planned_delivery)
        row.forecast_delivery = form_date("forecast_delivery", row.forecast_delivery)
        row.delivery_note_reference = form_str("delivery_note_reference",
                                               row.delivery_note_reference, 200)
        row.material_certificate_reference = form_str("material_certificate_reference",
                                                      row.material_certificate_reference, 200)
        row.allocated_area_id = form_int("allocated_area_id", row.allocated_area_id)
        row.low_stock_threshold_pct = form_float("low_stock_threshold_pct",
                                                 row.low_stock_threshold_pct)
        row.comments = form_str("comments", row.comments)
        db.session.commit()
        flash(t("Material updated."), "success")
        return redirect(url_for("procurement.material", material_id=material_id))

    as_of = request_date("as_of")
    return render_template(
        "procurement/material.html",
        view=procurement_service.material_view(row, as_of),
        as_of=as_of,
        deliveries=Delivery.query.filter_by(material_id=row.id)
                   .order_by(Delivery.delivery_date.desc()).all(),
        transactions=MaterialTransaction.query.filter_by(material_id=row.id)
                     .order_by(MaterialTransaction.transaction_date.desc()).all(),
        areas=Area.query.filter_by(active=True).order_by(Area.area_code).all(),
    )


@bp.route("/materials/<int:material_id>/delete", methods=["POST"])
def delete_material(material_id):
    row = Material.query.get_or_404(material_id)
    package_id = row.package_id
    db.session.delete(row)
    db.session.commit()
    flash(t("Material line removed."), "warning")
    return redirect(url_for("procurement.package", package_id=package_id))


# --------------------------------------------------------------------------
# Deliveries and stock movements
# --------------------------------------------------------------------------
@bp.route("/deliveries", methods=["GET", "POST"])
def deliveries():
    if request.method == "POST":
        material_id = form_int("material_id")
        row = db.session.get(Material, material_id) if material_id else None
        if row is None:
            flash(t("Select the material line the delivery belongs to."), "danger")
            return redirect(url_for("procurement.deliveries"))
        delivery = Delivery(
            material_id=row.id,
            package_id=row.package_id,
            delivery_date=form_date("delivery_date", date.today()),
            delivery_note_reference=form_str("delivery_note_reference", max_length=200),
            quantity=form_float("quantity", 0.0),
            unit=form_str("unit", row.unit, 30),
            status=form_str("status", "DELIVERED"),
            accepted_quantity=form_float("accepted_quantity", 0.0),
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
        if delivery.accepted_quantity:
            db.session.add(MaterialTransaction(
                material_id=row.id,
                transaction_date=delivery.delivery_date,
                transaction_type="RECEIPT ACCEPTED",
                quantity=delivery.accepted_quantity,
                area_id=delivery.area_id,
                reference=delivery.delivery_note_reference,
                comments="Created from an accepted delivery.",
            ))
        db.session.commit()
        flash(t("Delivery recorded. Delivered, accepted and installed remain separate quantities."), "success")
        return redirect(url_for("procurement.deliveries"))

    date_from = arg_date("from")
    date_to = arg_date("to")
    query = Delivery.query
    if date_from:
        query = query.filter(Delivery.delivery_date >= date_from)
    if date_to:
        query = query.filter(Delivery.delivery_date <= date_to)
    return render_template(
        "procurement/deliveries.html",
        rows=query.order_by(Delivery.delivery_date.desc()).all(),
        materials=Material.query.order_by(Material.item).all(),
        areas=Area.query.filter_by(active=True).order_by(Area.area_code).all(),
        date_from=date_from, date_to=date_to,
    )


@bp.route("/deliveries/<int:delivery_id>", methods=["POST"])
def update_delivery(delivery_id):
    row = Delivery.query.get_or_404(delivery_id)
    if form_str("action") == "delete":
        material = row.material
        db.session.delete(row)
        db.session.flush()
        if material:
            procurement_service.recalculate_material(material)
        db.session.commit()
        flash(t("Delivery removed and material totals recalculated."), "warning")
        return redirect(url_for("procurement.deliveries"))

    row.status = form_str("status", row.status)
    row.accepted_quantity = form_float("accepted_quantity", row.accepted_quantity)
    row.rejected_quantity = form_float("rejected_quantity", row.rejected_quantity)
    row.inspection_date = form_date("inspection_date", row.inspection_date)
    row.inspected_by = form_str("inspected_by", row.inspected_by, 160)
    row.certificate_reference = form_str("certificate_reference", row.certificate_reference, 200)
    row.comments = form_str("comments", row.comments)
    procurement_service.apply_delivery_to_material(row)
    db.session.commit()
    flash(t("Delivery updated."), "success")
    return redirect(request.referrer or url_for("procurement.deliveries"))


@bp.route("/materials/<int:material_id>/transactions", methods=["POST"])
def add_transaction(material_id):
    row = Material.query.get_or_404(material_id)
    txn_type = form_str("transaction_type", "ISSUE TO WORKFRONT")
    quantity = form_float("quantity", 0.0)
    if not quantity:
        flash(t("A quantity is required for a stock movement."), "danger")
        return redirect(url_for("procurement.material", material_id=material_id))
    db.session.add(MaterialTransaction(
        material_id=row.id,
        transaction_date=form_date("transaction_date", date.today()),
        transaction_type=txn_type,
        quantity=quantity,
        area_id=form_int("area_id"),
        reference=form_str("reference", max_length=200),
        comments=form_str("comments"),
    ))
    db.session.commit()
    flash(t("Stock movement recorded ({txn_type}).", txn_type=txn_type), "success")
    return redirect(url_for("procurement.material", material_id=material_id))


@bp.route("/transactions/<int:txn_id>/delete", methods=["POST"])
def delete_transaction(txn_id):
    row = MaterialTransaction.query.get_or_404(txn_id)
    material_id = row.material_id
    db.session.delete(row)
    db.session.commit()
    flash(t("Stock movement removed."), "warning")
    return redirect(url_for("procurement.material", material_id=material_id))


# --------------------------------------------------------------------------
# Exports
# --------------------------------------------------------------------------
@bp.route("/export/packages.csv")
def export_packages():
    filename, text = exporters.export_procurement()
    return csv_response(filename, text)


@bp.route("/export/materials.csv")
def export_materials():
    filename, text = exporters.export_materials()
    return csv_response(filename, text)


@bp.route("/export/deliveries.csv")
def export_deliveries():
    filename, text = exporters.export_deliveries(date_from=arg_date("from"),
                                                 date_to=arg_date("to"))
    return csv_response(filename, text)
