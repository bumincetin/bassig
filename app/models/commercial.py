"""Procurement packages, materials, deliveries and warehouse movements."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Index

from app.extensions import db


def _utcnow():
    """Current UTC time as a naive datetime.

    `datetime.utcnow()` is deprecated from Python 3.12; this keeps the stored
    value identical while using the supported timezone-aware clock.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


class ProcurementPackage(db.Model):
    """A major supply package tracked through the full procurement chain."""

    __tablename__ = "procurement_package"

    id = db.Column(db.Integer, primary_key=True)
    package_code = db.Column(db.String(40), unique=True, nullable=False, index=True)
    package_name = db.Column(db.String(200), nullable=False)
    category = db.Column(db.String(80), index=True)
    equipment = db.Column(db.String(300))
    approved_vendors = db.Column(db.Text)
    responsible_party = db.Column(db.String(160))
    stage = db.Column(db.String(40), default="REQUIRED", index=True)
    wbs_code = db.Column(db.String(60), index=True)
    po_reference = db.Column(db.String(160))
    planned_delivery = db.Column(db.Date, index=True)
    forecast_delivery = db.Column(db.Date, index=True)
    actual_delivery = db.Column(db.Date, index=True)
    fat_required = db.Column(db.Boolean, default=False, nullable=False)
    fat_status = db.Column(db.String(30), default="NOT REQUIRED")
    fat_date = db.Column(db.Date)
    source_document_id = db.Column(
        db.Integer, db.ForeignKey("source_document.id", ondelete="SET NULL"), index=True
    )
    comments = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=_utcnow)
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)

    source_document = db.relationship("SourceDocument")
    materials = db.relationship(
        "Material", back_populates="package",
        cascade="all, delete-orphan", passive_deletes=True,
    )

    def __repr__(self):
        return f"<ProcurementPackage {self.package_code} {self.package_name}>"


class Material(db.Model):
    """A material/equipment line inside a package.

    Delivered, accepted and installed are separate quantities and are never
    inferred from one another.
    """

    __tablename__ = "material"

    id = db.Column(db.Integer, primary_key=True)
    package_id = db.Column(
        db.Integer, db.ForeignKey("procurement_package.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    item = db.Column(db.String(300), nullable=False)
    manufacturer = db.Column(db.String(200))
    vendor = db.Column(db.String(200))
    approved_vendor = db.Column(db.Boolean, default=False, nullable=False)
    unit = db.Column(db.String(30))

    contract_quantity = db.Column(db.Float)
    total_required = db.Column(db.Float, default=0.0)
    ordered = db.Column(db.Float, default=0.0)
    manufactured = db.Column(db.Float, default=0.0)
    delivered = db.Column(db.Float, default=0.0)
    accepted = db.Column(db.Float, default=0.0)
    installed = db.Column(db.Float, default=0.0)

    po_reference = db.Column(db.String(160))
    fat_required = db.Column(db.Boolean, default=False, nullable=False)
    fat_status = db.Column(db.String(30), default="NOT REQUIRED")
    fat_date = db.Column(db.Date)

    planned_delivery = db.Column(db.Date, index=True)
    forecast_delivery = db.Column(db.Date, index=True)
    actual_delivery = db.Column(db.Date, index=True)
    delivery_note_reference = db.Column(db.String(200))
    material_certificate_reference = db.Column(db.String(200))

    allocated_area_id = db.Column(db.Integer, db.ForeignKey("area.id", ondelete="SET NULL"), index=True)
    low_stock_threshold_pct = db.Column(db.Float)
    source_document_id = db.Column(
        db.Integer, db.ForeignKey("source_document.id", ondelete="SET NULL"), index=True
    )
    comments = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=_utcnow)
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)

    package = db.relationship("ProcurementPackage", back_populates="materials")
    allocated_area = db.relationship("Area")
    source_document = db.relationship("SourceDocument")
    transactions = db.relationship(
        "MaterialTransaction", back_populates="material",
        cascade="all, delete-orphan", passive_deletes=True,
    )
    deliveries = db.relationship(
        "Delivery", back_populates="material",
        cascade="all, delete-orphan", passive_deletes=True,
    )

    __table_args__ = (Index("ix_material_pkg_item", "package_id", "item"),)

    def __repr__(self):
        return f"<Material {self.item}>"


class Delivery(db.Model):
    """One physical delivery against a material line."""

    __tablename__ = "delivery"

    id = db.Column(db.Integer, primary_key=True)
    material_id = db.Column(db.Integer, db.ForeignKey("material.id", ondelete="CASCADE"), index=True)
    package_id = db.Column(
        db.Integer, db.ForeignKey("procurement_package.id", ondelete="SET NULL"), index=True
    )
    delivery_date = db.Column(db.Date, nullable=False, index=True)
    delivery_note_reference = db.Column(db.String(200))
    quantity = db.Column(db.Float, default=0.0)
    unit = db.Column(db.String(30))
    status = db.Column(db.String(30), default="DELIVERED", index=True)
    accepted_quantity = db.Column(db.Float, default=0.0)
    rejected_quantity = db.Column(db.Float, default=0.0)
    inspection_date = db.Column(db.Date)
    inspected_by = db.Column(db.String(160))
    certificate_reference = db.Column(db.String(200))
    area_id = db.Column(db.Integer, db.ForeignKey("area.id", ondelete="SET NULL"), index=True)
    comments = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=_utcnow)

    material = db.relationship("Material", back_populates="deliveries")
    package = db.relationship("ProcurementPackage")
    area = db.relationship("Area")

    def __repr__(self):
        return f"<Delivery {self.delivery_date} {self.delivery_note_reference}>"


class MaterialTransaction(db.Model):
    """Warehouse movement.

    available = accepted receipts + adjustments - issued to workfront
    """

    __tablename__ = "material_transaction"

    id = db.Column(db.Integer, primary_key=True)
    material_id = db.Column(
        db.Integer, db.ForeignKey("material.id", ondelete="CASCADE"), nullable=False, index=True
    )
    transaction_date = db.Column(db.Date, nullable=False, index=True)
    transaction_type = db.Column(db.String(40), nullable=False, index=True)
    quantity = db.Column(db.Float, nullable=False, default=0.0)
    area_id = db.Column(db.Integer, db.ForeignKey("area.id", ondelete="SET NULL"), index=True)
    reference = db.Column(db.String(200))
    comments = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=_utcnow)

    material = db.relationship("Material", back_populates="transactions")
    area = db.relationship("Area")

    def __repr__(self):
        return f"<MaterialTransaction {self.transaction_type} {self.quantity}>"


class PaymentMilestone(db.Model):
    """Contractual payment milestone (EPC Contract Schedule 10 - Payment).

    Percentages come from the contract; the amount is derived from the
    registered Contract Price. Certification and invoicing are recorded facts,
    never inferred from physical progress.
    """

    __tablename__ = "payment_milestone"

    id = db.Column(db.Integer, primary_key=True)
    sequence = db.Column(db.Integer, default=0, index=True)
    milestone_code = db.Column(db.String(40), unique=True, index=True)
    description = db.Column(db.String(400), nullable=False)
    percentage = db.Column(db.Float, nullable=False, default=0.0)
    # Optional links to the physical work that evidences the milestone.
    wbs_code = db.Column(db.String(60), index=True)
    gate_code = db.Column(db.String(4), index=True)
    package_code = db.Column(db.String(40), index=True)

    planned_date = db.Column(db.Date, index=True)
    forecast_date = db.Column(db.Date, index=True)
    achieved_date = db.Column(db.Date, index=True)
    certified_date = db.Column(db.Date)
    invoiced_date = db.Column(db.Date)
    paid_date = db.Column(db.Date)
    status = db.Column(db.String(30), default="NOT STARTED", nullable=False, index=True)
    evidence_reference = db.Column(db.String(300))
    source_document_id = db.Column(
        db.Integer, db.ForeignKey("source_document.id", ondelete="SET NULL"), index=True
    )
    comments = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=_utcnow)
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)

    source_document = db.relationship("SourceDocument")

    def amount(self, contract_price):
        if contract_price is None or self.percentage is None:
            return None
        return float(contract_price) * float(self.percentage) / 100.0

    def __repr__(self):
        return f"<PaymentMilestone {self.milestone_code} {self.percentage}%>"
