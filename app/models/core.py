"""Project master data: project identity, settings, source documents,
schedule versions, WBS activities, areas, quantities, contractors.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import Index

from app.extensions import db


def _utcnow():
    """Current UTC time as a naive datetime.

    `datetime.utcnow()` is deprecated from Python 3.12; this keeps the stored
    value identical while using the supported timezone-aware clock.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Project(db.Model):
    """Single-project master record (this build is Bassignana Solar 2 only)."""

    __tablename__ = "project"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False, default="Bassignana Solar 2")
    subtitle = db.Column(db.String(250), default="Project & Site Control System")
    plant_name = db.Column(db.String(200))
    client = db.Column(db.String(200))
    epc_contractor = db.Column(db.String(200))
    contract_reference = db.Column(db.String(200))
    ntp_date = db.Column(db.Date)
    contract_completion_date = db.Column(db.Date)

    comune = db.Column(db.String(120))
    provincia = db.Column(db.String(120))
    regione = db.Column(db.String(120))
    country = db.Column(db.String(80), default="Italy")

    nominal_dc_kwp = db.Column(db.Float)
    nominal_ac_kw = db.Column(db.Float)
    grid_voltage_kv = db.Column(db.Float)
    dso = db.Column(db.String(120))
    pod_code = db.Column(db.String(60))
    authorisation_reference = db.Column(db.String(200))
    cadastral_reference = db.Column(db.String(400))

    # Commercial and contractual parameters, from the signed EPC Contract.
    contract_price = db.Column(db.Float)
    currency = db.Column(db.String(10), default="EUR")
    delay_lds_pct_per_day = db.Column(db.Float)
    delay_lds_cap_pct = db.Column(db.Float)
    delay_termination_days = db.Column(db.Integer)
    performance_bond_pct = db.Column(db.Float)
    advance_payment_pct = db.Column(db.Float)
    dnp_months = db.Column(db.Integer)
    guaranteed_pr_note = db.Column(db.String(300))
    min_availability_pct = db.Column(db.Float)

    # Contractual adverse-weather thresholds for extension-of-time claims
    # (EPC Contract Sub-Clause 8.4(iv)).
    adverse_wind_ms = db.Column(db.Float)
    adverse_rain_mm_h = db.Column(db.Float)

    setup_complete = db.Column(db.Boolean, default=False, nullable=False)
    setup_step = db.Column(db.Integer, default=1, nullable=False)
    notes = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=_utcnow)
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)

    def __repr__(self):
        return f"<Project {self.name}>"


class ProjectSetting(db.Model):
    """Configurable thresholds and operating parameters."""

    __tablename__ = "project_setting"

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(80), unique=True, nullable=False, index=True)
    value = db.Column(db.String(255))
    value_type = db.Column(db.String(20), default="float")  # float | int | str | bool
    category = db.Column(db.String(60), default="General")
    description = db.Column(db.String(400))
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)

    def typed(self):
        raw = self.value
        if raw is None or raw == "":
            return None
        try:
            if self.value_type == "float":
                return float(raw)
            if self.value_type == "int":
                return int(float(raw))
            if self.value_type == "bool":
                return str(raw).strip().lower() in {"1", "true", "yes", "on"}
        except (TypeError, ValueError):
            return None
        return raw

    def __repr__(self):
        return f"<ProjectSetting {self.key}={self.value}>"


class SourceDocument(db.Model):
    """Register of the authoritative Bassignana project documents.

    Nothing in the application may claim a data provenance that is not
    represented by a row in this table.
    """

    __tablename__ = "source_document"

    id = db.Column(db.Integer, primary_key=True)
    document_type = db.Column(db.String(60), nullable=False, index=True)
    title = db.Column(db.String(300), nullable=False)
    source_filename = db.Column(db.String(300))
    stored_path = db.Column(db.String(500))
    revision = db.Column(db.String(60))
    document_date = db.Column(db.Date, index=True)
    effective_date = db.Column(db.Date)
    status = db.Column(db.String(40), nullable=False, default="DRAFT", index=True)
    contractual = db.Column(db.Boolean, default=False, nullable=False)
    supersedes_document_id = db.Column(
        db.Integer, db.ForeignKey("source_document.id", ondelete="SET NULL"), index=True
    )
    source_reference = db.Column(db.String(300))
    notes = db.Column(db.Text)
    imported_at = db.Column(db.DateTime, default=_utcnow)

    supersedes = db.relationship("SourceDocument", remote_side=[id], backref="superseded_by")

    @property
    def label(self):
        rev = f" rev. {self.revision}" if self.revision else ""
        return f"{self.title}{rev}"

    def __repr__(self):
        return f"<SourceDocument {self.title} [{self.status}]>"


class ImportBatch(db.Model):
    """One committed data import. Never deleted, so provenance survives."""

    __tablename__ = "import_batch"

    id = db.Column(db.Integer, primary_key=True)
    import_type = db.Column(db.String(60), nullable=False, index=True)
    filename = db.Column(db.String(300))
    source_document_id = db.Column(
        db.Integer, db.ForeignKey("source_document.id", ondelete="SET NULL"), index=True
    )
    schedule_version_id = db.Column(
        db.Integer, db.ForeignKey("schedule_version.id", ondelete="SET NULL"), index=True
    )
    row_count = db.Column(db.Integer, default=0)
    created_count = db.Column(db.Integer, default=0)
    updated_count = db.Column(db.Integer, default=0)
    skipped_count = db.Column(db.Integer, default=0)
    error_count = db.Column(db.Integer, default=0)
    status = db.Column(db.String(30), default="COMMITTED")
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=_utcnow, index=True)

    source_document = db.relationship("SourceDocument")

    def __repr__(self):
        return f"<ImportBatch {self.import_type} {self.created_at:%Y-%m-%d}>"


class ScheduleVersion(db.Model):
    """A programme revision. Baselines and working plans never share a row."""

    __tablename__ = "schedule_version"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    revision = db.Column(db.String(60))
    schedule_type = db.Column(db.String(40), nullable=False, index=True)
    issue_date = db.Column(db.Date)
    effective_date = db.Column(db.Date, index=True)
    status = db.Column(db.String(30), default="ACTIVE", index=True)
    source_document_id = db.Column(
        db.Integer, db.ForeignKey("source_document.id", ondelete="SET NULL"), index=True
    )
    is_contractual_baseline = db.Column(db.Boolean, default=False, nullable=False, index=True)
    is_current_working = db.Column(db.Boolean, default=False, nullable=False, index=True)
    locked = db.Column(db.Boolean, default=False, nullable=False)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=_utcnow)

    source_document = db.relationship("SourceDocument")
    activities = db.relationship(
        "WbsActivity", back_populates="schedule_version",
        cascade="all, delete-orphan", passive_deletes=True,
    )

    @property
    def label(self):
        rev = f" rev. {self.revision}" if self.revision else ""
        return f"{self.name}{rev}"

    def __repr__(self):
        return f"<ScheduleVersion {self.name} [{self.schedule_type}]>"


class WbsActivity(db.Model):
    """One WBS activity inside one schedule version."""

    __tablename__ = "wbs_activity"

    id = db.Column(db.Integer, primary_key=True)
    schedule_version_id = db.Column(
        db.Integer, db.ForeignKey("schedule_version.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    wbs_code = db.Column(db.String(60), nullable=False, index=True)
    parent_wbs_code = db.Column(db.String(60), index=True)
    activity_name = db.Column(db.String(400), nullable=False)
    work_package = db.Column(db.String(200), index=True)
    discipline = db.Column(db.String(60), index=True)
    level = db.Column(db.Integer, default=1, index=True)
    sort_index = db.Column(db.Integer, default=0, index=True)

    # Contractual dates. Populated only on CONTRACTUAL BASELINE versions,
    # or carried across by the comparison service; never overwritten by an update.
    baseline_start = db.Column(db.Date, index=True)
    baseline_finish = db.Column(db.Date, index=True)

    plan_start = db.Column(db.Date, index=True)
    plan_finish = db.Column(db.Date, index=True)
    actual_start = db.Column(db.Date, index=True)
    actual_finish = db.Column(db.Date, index=True)

    duration_days = db.Column(db.Float)
    is_milestone = db.Column(db.Boolean, default=False, nullable=False, index=True)

    unit = db.Column(db.String(30))
    total_required_quantity = db.Column(db.Float)
    progress_weight = db.Column(db.Float)
    weight_basis = db.Column(db.String(30), default="NOT SET")
    progress_method = db.Column(db.String(20), default="MANUAL")

    # Percentage reported in the source programme or entered by hand.
    reported_completion_pct = db.Column(db.Float, default=0.0)
    manual_pct = db.Column(db.Boolean, default=True, nullable=False)

    responsible_party = db.Column(db.String(160))
    status = db.Column(db.String(30), default="NOT STARTED", index=True)
    # Manual override linking this activity back to a baseline WBS code when
    # the code changed between revisions.
    baseline_link_wbs = db.Column(db.String(60), index=True)
    source_document_id = db.Column(
        db.Integer, db.ForeignKey("source_document.id", ondelete="SET NULL"), index=True
    )
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=_utcnow)
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)

    schedule_version = db.relationship("ScheduleVersion", back_populates="activities")
    source_document = db.relationship("SourceDocument")

    __table_args__ = (
        Index("ix_wbs_version_code", "schedule_version_id", "wbs_code", unique=True),
        Index("ix_wbs_version_parent", "schedule_version_id", "parent_wbs_code"),
    )

    @property
    def is_summary(self):
        """True when other activities in the same version hang off this one."""
        return bool(self._child_count) if self._child_count is not None else False

    _child_count = None

    def __repr__(self):
        return f"<WbsActivity {self.wbs_code} {self.activity_name[:40]}>"


class Area(db.Model):
    """Workfront / area of the plant. Never seeded with invented codes."""

    __tablename__ = "area"

    id = db.Column(db.Integer, primary_key=True)
    area_code = db.Column(db.String(60), nullable=False, unique=True, index=True)
    area_name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    parent_area_id = db.Column(db.Integer, db.ForeignKey("area.id", ondelete="SET NULL"), index=True)
    drawing_reference = db.Column(db.String(200))
    ifc_revision = db.Column(db.String(60))
    active = db.Column(db.Boolean, default=True, nullable=False, index=True)
    source_document_id = db.Column(
        db.Integer, db.ForeignKey("source_document.id", ondelete="SET NULL"), index=True
    )
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=_utcnow)

    parent = db.relationship("Area", remote_side=[id], backref="children")
    source_document = db.relationship("SourceDocument")

    @property
    def label(self):
        return f"{self.area_code} - {self.area_name}"

    def __repr__(self):
        return f"<Area {self.area_code}>"


class ActivityQuantity(db.Model):
    """BOQ / quantity register entry, always tied to a source document."""

    __tablename__ = "activity_quantity"

    id = db.Column(db.Integer, primary_key=True)
    wbs_code = db.Column(db.String(60), index=True)
    area_id = db.Column(db.Integer, db.ForeignKey("area.id", ondelete="SET NULL"), index=True)
    activity_name = db.Column(db.String(300))
    item = db.Column(db.String(300), nullable=False)
    total_quantity = db.Column(db.Float, nullable=False, default=0.0)
    unit = db.Column(db.String(30))
    source_document_id = db.Column(
        db.Integer, db.ForeignKey("source_document.id", ondelete="SET NULL"), index=True
    )
    source_reference = db.Column(db.String(300))
    revision = db.Column(db.String(60))
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=_utcnow)

    area = db.relationship("Area")
    source_document = db.relationship("SourceDocument")

    def __repr__(self):
        return f"<ActivityQuantity {self.item} {self.total_quantity}{self.unit or ''}>"


class Contractor(db.Model):
    """EPC contractor, subcontractors, client and third parties on site."""

    __tablename__ = "contractor"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False, unique=True)
    short_name = db.Column(db.String(60))
    role = db.Column(db.String(40), default="SUBCONTRACTOR", index=True)
    discipline = db.Column(db.String(60))
    contact = db.Column(db.String(200))
    active = db.Column(db.Boolean, default=True, nullable=False, index=True)
    notes = db.Column(db.Text)

    def __repr__(self):
        return f"<Contractor {self.name}>"
