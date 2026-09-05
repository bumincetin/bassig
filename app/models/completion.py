"""Permits, document register and contractual acceptance gates."""
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


class PermitItem(db.Model):
    """Permit / readiness register entry.

    Status register only. The application never offers legal interpretation.
    """

    __tablename__ = "permit_item"

    id = db.Column(db.Integer, primary_key=True)
    item_name = db.Column(db.String(300), nullable=False)
    authority = db.Column(db.String(200), index=True)
    responsibility = db.Column(db.String(160))
    required_for = db.Column(db.String(300))
    required_by_date = db.Column(db.Date, index=True)
    issued_date = db.Column(db.Date)
    expiry_date = db.Column(db.Date, index=True)
    status = db.Column(db.String(30), default="NOT STARTED", nullable=False, index=True)
    document_reference = db.Column(db.String(300))
    blocker_impact = db.Column(db.Text)
    source_document_id = db.Column(
        db.Integer, db.ForeignKey("source_document.id", ondelete="SET NULL"), index=True
    )
    verified = db.Column(db.Boolean, default=False, nullable=False)
    comments = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=_utcnow)
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)

    source_document = db.relationship("SourceDocument")

    def __repr__(self):
        return f"<PermitItem {self.item_name[:40]} [{self.status}]>"


class DocumentRegisterItem(db.Model):
    """Lightweight register of required project evidence documents."""

    __tablename__ = "document_register_item"

    id = db.Column(db.Integer, primary_key=True)
    document_number = db.Column(db.String(120), index=True)
    title = db.Column(db.String(400), nullable=False)
    category = db.Column(db.String(60), index=True)
    discipline = db.Column(db.String(60), index=True)
    wbs_code = db.Column(db.String(60), index=True)
    revision = db.Column(db.String(60))
    status = db.Column(db.String(30), default="NOT STARTED", nullable=False, index=True)
    issue_date = db.Column(db.Date)
    required_date = db.Column(db.Date, index=True)
    submitted_date = db.Column(db.Date)
    accepted_date = db.Column(db.Date)
    source_path = db.Column(db.String(500))
    # Acceptance gate that requires this document (A/B/C/D), if any.
    gate_code = db.Column(db.String(4), index=True)
    mandatory = db.Column(db.Boolean, default=True, nullable=False, index=True)
    folder_path = db.Column(db.String(400))
    source_document_id = db.Column(
        db.Integer, db.ForeignKey("source_document.id", ondelete="SET NULL"), index=True
    )
    remarks = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=_utcnow)
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)

    source_document = db.relationship("SourceDocument")

    __table_args__ = (Index("ix_doc_gate_mandatory", "gate_code", "mandatory", "status"),)

    def __repr__(self):
        return f"<DocumentRegisterItem {self.title[:40]} [{self.status}]>"


class AcceptanceGate(db.Model):
    """One of the four contractual acceptance gates."""

    __tablename__ = "acceptance_gate"

    id = db.Column(db.Integer, primary_key=True)
    gate_code = db.Column(db.String(4), unique=True, nullable=False, index=True)
    name = db.Column(db.String(160), nullable=False)
    description = db.Column(db.Text)
    sequence = db.Column(db.Integer, default=0)
    contract_reference = db.Column(db.String(200))
    target_date = db.Column(db.Date)
    actual_date = db.Column(db.Date)
    # Acceptance is always recorded by a person; never set by the application.
    status = db.Column(db.String(30), default="NOT STARTED", nullable=False, index=True)
    accepted_by = db.Column(db.String(160))
    source_document_id = db.Column(
        db.Integer, db.ForeignKey("source_document.id", ondelete="SET NULL"), index=True
    )
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=_utcnow)
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)

    source_document = db.relationship("SourceDocument")
    items = db.relationship(
        "AcceptanceGateItem", back_populates="gate",
        cascade="all, delete-orphan", passive_deletes=True,
        order_by="AcceptanceGateItem.sequence",
    )

    def __repr__(self):
        return f"<AcceptanceGate {self.gate_code} {self.name}>"


class AcceptanceGateItem(db.Model):
    """A single prerequisite of an acceptance gate."""

    __tablename__ = "acceptance_gate_item"

    id = db.Column(db.Integer, primary_key=True)
    gate_id = db.Column(
        db.Integer, db.ForeignKey("acceptance_gate.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    item_code = db.Column(db.String(40), index=True)
    item_name = db.Column(db.String(400), nullable=False)
    description = db.Column(db.Text)
    category = db.Column(db.String(80), index=True)
    responsible_party = db.Column(db.String(160))
    target_date = db.Column(db.Date, index=True)
    actual_date = db.Column(db.Date)
    status = db.Column(db.String(30), default="NOT STARTED", nullable=False, index=True)
    evidence_reference = db.Column(db.String(400))
    contract_reference = db.Column(db.String(200))
    sequence = db.Column(db.Integer, default=0, index=True)
    source_document_id = db.Column(
        db.Integer, db.ForeignKey("source_document.id", ondelete="SET NULL"), index=True
    )
    comments = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=_utcnow)
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)

    gate = db.relationship("AcceptanceGate", back_populates="items")
    source_document = db.relationship("SourceDocument")

    __table_args__ = (Index("ix_gate_item_status", "gate_id", "status"),)

    def __repr__(self):
        return f"<AcceptanceGateItem {self.item_name[:40]} [{self.status}]>"
