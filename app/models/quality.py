"""Quality management, inspection requirements, RFIs and the action register."""
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


class InspectionRequirement(db.Model):
    """An ITP / checklist point required by the contract or QA plan."""

    __tablename__ = "inspection_requirement"

    id = db.Column(db.Integer, primary_key=True)
    wbs_code = db.Column(db.String(60), index=True)
    work_package = db.Column(db.String(200), index=True)
    itp_reference = db.Column(db.String(120), index=True)
    inspection_type = db.Column(db.String(80))
    point_type = db.Column(db.String(20), default="REVIEW", index=True)
    required_evidence = db.Column(db.Text)
    acceptance_criterion = db.Column(db.Text)
    applicable_specification = db.Column(db.String(300))
    discipline = db.Column(db.String(60), index=True)
    source_document_id = db.Column(
        db.Integer, db.ForeignKey("source_document.id", ondelete="SET NULL"), index=True
    )
    active = db.Column(db.Boolean, default=True, nullable=False, index=True)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=_utcnow)

    source_document = db.relationship("SourceDocument")

    def __repr__(self):
        return f"<InspectionRequirement {self.itp_reference}>"


class QualityRecord(db.Model):
    """Inspection, ITP point, checklist, NCR, corrective action, punch item
    or test record.

    Record types share one workflow engine but stay semantically separate --
    a punch item is never reported as an NCR and vice versa.
    """

    __tablename__ = "quality_record"

    id = db.Column(db.Integer, primary_key=True)
    record_number = db.Column(db.String(40), unique=True, nullable=False, index=True)
    record_type = db.Column(db.String(30), nullable=False, index=True)
    record_date = db.Column(db.Date, nullable=False, index=True)

    wbs_code = db.Column(db.String(60), index=True)
    work_package = db.Column(db.String(200), index=True)
    area_id = db.Column(db.Integer, db.ForeignKey("area.id", ondelete="SET NULL"), index=True)
    discipline = db.Column(db.String(60), index=True)

    specification_reference = db.Column(db.String(300))
    drawing_reference = db.Column(db.String(300))
    itp_reference = db.Column(db.String(120), index=True)
    inspection_requirement_id = db.Column(
        db.Integer, db.ForeignKey("inspection_requirement.id", ondelete="SET NULL"), index=True
    )

    title = db.Column(db.String(300))
    description = db.Column(db.Text)
    responsible_party = db.Column(db.String(160))
    raised_by = db.Column(db.String(160))
    severity = db.Column(db.String(20), default="MEDIUM", index=True)
    target_closure_date = db.Column(db.Date, index=True)
    status = db.Column(db.String(30), default="OPEN", nullable=False, index=True)
    inspection_result = db.Column(db.String(30))
    corrective_action = db.Column(db.Text)
    evidence_reference = db.Column(db.String(300))
    closure_date = db.Column(db.Date, index=True)
    # Punch items agreed at an acceptance gate carry the gate code.
    gate_code = db.Column(db.String(4), index=True)
    comments = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=_utcnow)
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)

    area = db.relationship("Area")
    inspection_requirement = db.relationship("InspectionRequirement")
    photos = db.relationship("Photo", back_populates="quality_record")

    __table_args__ = (
        Index("ix_qr_type_status", "record_type", "status"),
        Index("ix_qr_type_target", "record_type", "target_closure_date"),
    )

    def __repr__(self):
        return f"<QualityRecord {self.record_number} [{self.status}]>"


class Rfi(db.Model):
    """Request for information / technical query."""

    __tablename__ = "rfi"

    id = db.Column(db.Integer, primary_key=True)
    rfi_number = db.Column(db.String(40), unique=True, nullable=False, index=True)
    date_raised = db.Column(db.Date, nullable=False, index=True)
    raised_by = db.Column(db.String(160))
    area_id = db.Column(db.Integer, db.ForeignKey("area.id", ondelete="SET NULL"), index=True)
    wbs_code = db.Column(db.String(60), index=True)
    discipline = db.Column(db.String(60), index=True)
    subject = db.Column(db.String(300), nullable=False)
    question = db.Column(db.Text)
    reference = db.Column(db.String(300))
    responsible_party = db.Column(db.String(160))
    required_response_date = db.Column(db.Date, index=True)
    response_date = db.Column(db.Date)
    status = db.Column(db.String(20), default="OPEN", nullable=False, index=True)
    response = db.Column(db.Text)
    schedule_impact = db.Column(db.Boolean, default=False, nullable=False, index=True)
    estimated_delay_days = db.Column(db.Float)
    blocker_id = db.Column(db.Integer, db.ForeignKey("blocker.id", ondelete="SET NULL"), index=True)
    comments = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=_utcnow)
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)

    area = db.relationship("Area")
    blocker = db.relationship("Blocker")
    photos = db.relationship("Photo", back_populates="rfi")

    def __repr__(self):
        return f"<Rfi {self.rfi_number} [{self.status}]>"


class Issue(db.Model):
    """General project action / issue register entry."""

    __tablename__ = "issue"

    id = db.Column(db.Integer, primary_key=True)
    issue_number = db.Column(db.String(40), unique=True, nullable=False, index=True)
    date_raised = db.Column(db.Date, nullable=False, index=True)
    title = db.Column(db.String(300), nullable=False)
    description = db.Column(db.Text)
    category = db.Column(db.String(40), index=True)
    area_id = db.Column(db.Integer, db.ForeignKey("area.id", ondelete="SET NULL"), index=True)
    wbs_code = db.Column(db.String(60), index=True)
    priority = db.Column(db.String(20), default="MEDIUM", index=True)
    raised_by = db.Column(db.String(160))
    responsible_party = db.Column(db.String(160))
    target_date = db.Column(db.Date, index=True)
    status = db.Column(db.String(20), default="OPEN", nullable=False, index=True)
    action = db.Column(db.Text)
    closed_date = db.Column(db.Date)
    comments = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=_utcnow)
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)

    area = db.relationship("Area")

    def __repr__(self):
        return f"<Issue {self.issue_number} [{self.status}]>"
