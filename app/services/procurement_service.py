"""Procurement, delivery and warehouse logic.

Delivered, accepted and installed are three different quantities. Nothing in
this module promotes one into another.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import func

from app import constants as C
from app.extensions import db
from app.i18n import translate as t
from app.models import Delivery, Material, MaterialTransaction, ProcurementPackage
from app.services.calculations import available_stock, pct
from app.services.status_rules import procurement_status, stock_status


def stock_for(material):
    """available = accepted receipts + adjustments - issued to workfront."""
    rows = (db.session.query(
        MaterialTransaction.transaction_type,
        func.coalesce(func.sum(MaterialTransaction.quantity), 0.0))
        .filter(MaterialTransaction.material_id == material.id)
        .group_by(MaterialTransaction.transaction_type).all())
    totals = {t: float(q or 0.0) for t, q in rows}
    receipts = totals.get("RECEIPT ACCEPTED", 0.0)
    adjustments = totals.get("ADJUSTMENT", 0.0)
    returns = totals.get("RETURN TO STORE", 0.0)
    issued = totals.get("ISSUE TO WORKFRONT", 0.0)
    # INSTALLED IN WORKS is deliberately absent: the material left the store when
    # it was issued, so counting installation again would double-deduct it.
    return available_stock(receipts + returns, adjustments, issued)


def material_view(material, as_of=None):
    """Everything the UI needs about one material line."""
    as_of = as_of or date.today()
    available = stock_for(material)
    required = float(material.total_required or 0.0)
    installed = float(material.installed or 0.0)
    remaining_requirement = max(required - installed, 0.0)
    return {
        "material": material,
        "available": available,
        "remaining_requirement": remaining_requirement,
        "stock_status": stock_status(available, remaining_requirement),
        "procurement_status": procurement_status(material, as_of),
        "delivered_pct": pct(material.delivered, required, cap=None),
        "accepted_pct": pct(material.accepted, required, cap=None),
        "installed_pct": pct(material.installed, required, cap=None),
        "ordered_pct": pct(material.ordered, required, cap=None),
        "shortfall_ordered": max(required - float(material.ordered or 0.0), 0.0),
        "shortfall_delivered": max(required - float(material.delivered or 0.0), 0.0),
        "shortfall_accepted": max(required - float(material.accepted or 0.0), 0.0),
    }


def package_view(package, as_of=None):
    as_of = as_of or date.today()
    materials = package.materials
    views = [material_view(m, as_of) for m in materials]
    late = [v for v in views if v["procurement_status"] == "LATE"]
    at_risk = [v for v in views if v["procurement_status"] == "AT RISK"]
    shortages = [v for v in views if v["stock_status"] == C.STOCK_SHORTAGE]
    return {
        "package": package,
        "materials": views,
        "status": procurement_status(package, as_of),
        "late_count": len(late),
        "at_risk_count": len(at_risk),
        "shortage_count": len(shortages),
        "stage_index": (C.PROCUREMENT_STAGES.index(package.stage)
                        if package.stage in C.PROCUREMENT_STAGES else 0),
        "stage_pct": pct(
            (C.PROCUREMENT_STAGES.index(package.stage) + 1)
            if package.stage in C.PROCUREMENT_STAGES else 0,
            len(C.PROCUREMENT_STAGES), cap=100.0),
    }


def all_package_views(as_of=None):
    packages = ProcurementPackage.query.order_by(ProcurementPackage.package_code).all()
    return [package_view(p, as_of) for p in packages]


def procurement_warnings(as_of=None):
    """Late deliveries, shortages and unapproved vendors, for the dashboard."""
    as_of = as_of or date.today()
    late_packages, at_risk_packages, shortages, unapproved, fat_issues = [], [], [], [], []

    for package in ProcurementPackage.query.all():
        status = procurement_status(package, as_of)
        if status == "LATE":
            late_packages.append(package)
        elif status == "AT RISK":
            at_risk_packages.append(package)
        if package.fat_required and (package.fat_status or "").upper() in {"FAILED", "NOT STARTED"}:
            fat_issues.append(package)

    for material in Material.query.all():
        view = material_view(material, as_of)
        if view["stock_status"] in {C.STOCK_SHORTAGE, C.STOCK_LOW}:
            shortages.append(view)
        if material.vendor and not material.approved_vendor:
            unapproved.append(material)

    return {
        "late_packages": late_packages,
        "at_risk_packages": at_risk_packages,
        "shortages": shortages,
        "unapproved_vendors": unapproved,
        "fat_issues": fat_issues,
        "late_count": len(late_packages),
        "warning_count": len(late_packages) + len(at_risk_packages) + len(shortages)
                          + len(unapproved) + len(fat_issues),
    }


def stage_distribution():
    """Count of packages in each procurement stage, in contractual order."""
    counts = dict(db.session.query(
        ProcurementPackage.stage, func.count(ProcurementPackage.id)
    ).group_by(ProcurementPackage.stage).all())
    return [{"stage": stage, "count": int(counts.get(stage, 0))} for stage in C.PROCUREMENT_STAGES]


def recent_deliveries(limit=20, since=None, until=None):
    query = Delivery.query
    if since:
        query = query.filter(Delivery.delivery_date >= since)
    if until:
        query = query.filter(Delivery.delivery_date <= until)
    return query.order_by(Delivery.delivery_date.desc(), Delivery.id.desc()).limit(limit).all()


def recalculate_material(material):
    """Recompute a material's delivered/accepted totals from its deliveries.

    Deliveries are the record of truth; the material header simply reflects
    them. The installed quantity is a site fact and is never touched here.
    """
    if material is None:
        return
    rows = Delivery.query.filter_by(material_id=material.id).all()
    material.delivered = sum(float(d.quantity or 0.0) for d in rows)
    material.accepted = sum(float(d.accepted_quantity or 0.0) for d in rows)
    dates = [d.delivery_date for d in rows if d.delivery_date]
    material.actual_delivery = max(dates) if dates else None


def apply_delivery_to_material(delivery):
    """Recalculate the material behind a delivery record."""
    if delivery is None:
        return
    recalculate_material(delivery.material)


def recalculate_installed(material):
    """Set the installed quantity from the recorded installation movements.

    Installation is built up day by day from the site diary, so the movements
    are the record of truth and the header figure simply reflects them.
    """
    if material is None:
        return
    total = (db.session.query(func.coalesce(func.sum(MaterialTransaction.quantity), 0.0))
             .filter(MaterialTransaction.material_id == material.id,
                     MaterialTransaction.transaction_type.in_(sorted(C.MATERIAL_TXN_INSTALL)))
             .scalar())
    material.installed = float(total or 0.0)


def record_installation(material, quantity, on_date, area_id=None, reference=None,
                        comments=None):
    """Record material fixed in the works on a given day.

    If the material already carried an installed quantity that was typed in
    directly, an opening-balance movement is written first so that figure is
    preserved rather than silently overwritten by the first daily entry.
    """
    if material is None or not quantity:
        return None

    has_history = (MaterialTransaction.query
                   .filter(MaterialTransaction.material_id == material.id,
                           MaterialTransaction.transaction_type.in_(
                               sorted(C.MATERIAL_TXN_INSTALL)))
                   .first() is not None)
    opening = float(material.installed or 0.0)
    if not has_history and opening > 0:
        db.session.add(MaterialTransaction(
            material_id=material.id, transaction_date=on_date,
            transaction_type="INSTALLED IN WORKS", quantity=opening,
            reference=t("Opening balance"),
            comments="Installed quantity recorded before daily installation "
                     "tracking began."))

    movement = MaterialTransaction(
        material_id=material.id, transaction_date=on_date,
        transaction_type="INSTALLED IN WORKS", quantity=float(quantity),
        area_id=area_id, reference=reference, comments=comments)
    db.session.add(movement)
    db.session.flush()
    recalculate_installed(material)
    return movement


def installed_on(material, on_date):
    """Quantity of one material recorded as installed on a given day."""
    total = (db.session.query(func.coalesce(func.sum(MaterialTransaction.quantity), 0.0))
             .filter(MaterialTransaction.material_id == material.id,
                     MaterialTransaction.transaction_date == on_date,
                     MaterialTransaction.transaction_type.in_(
                         sorted(C.MATERIAL_TXN_INSTALL)))
             .scalar())
    return float(total or 0.0)


def day_movements(on_date):
    """Every delivery and stock movement recorded on one day."""
    deliveries = (Delivery.query.filter_by(delivery_date=on_date)
                  .order_by(Delivery.id).all())
    movements = (MaterialTransaction.query.filter_by(transaction_date=on_date)
                 .order_by(MaterialTransaction.id).all())
    return {"deliveries": deliveries, "movements": movements}
