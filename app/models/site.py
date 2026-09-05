"""Daily site execution records: diary, progress, workforce, plant,
observations, blockers and photographs.
"""
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


def _safe_div(numerator, denominator):
    """Division that never raises and never returns a misleading zero."""
    try:
        if denominator in (None, 0) or numerator is None:
            return None
        return float(numerator) / float(denominator)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


class DailySiteReport(db.Model):
    """Header of one day of site reporting."""

    __tablename__ = "daily_site_report"

    id = db.Column(db.Integer, primary_key=True)
    report_date = db.Column(db.Date, nullable=False, unique=True, index=True)
    report_number = db.Column(db.String(40), unique=True, index=True)
    weather = db.Column(db.String(60))
    weather_pm = db.Column(db.String(60))
    temperature_min_c = db.Column(db.Float)
    temperature_max_c = db.Column(db.Float)
    shift = db.Column(db.String(30), default="DAY")
    prepared_by = db.Column(db.String(160))
    contractor_id = db.Column(db.Integer, db.ForeignKey("contractor.id", ondelete="SET NULL"), index=True)
    subcontractors = db.Column(db.String(400))
    work_start_time = db.Column(db.String(10))
    work_end_time = db.Column(db.String(10))
    # Contractual adverse-weather measurements. The EPC Contract grants an
    # extension of time only for wind above 30 m/s or rainfall above 10 mm/h,
    # measured by calibrated site instrumentation, so both are recorded here.
    max_wind_ms = db.Column(db.Float)
    max_rain_mm_h = db.Column(db.Float)
    adverse_weather_claimed = db.Column(db.Boolean, default=False, nullable=False, index=True)
    general_comments = db.Column(db.Text)
    upcoming_work = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=_utcnow)
    updated_at = db.Column(db.DateTime, default=_utcnow, onupdate=_utcnow)

    contractor = db.relationship("Contractor")
    progress_entries = db.relationship(
        "DailyProgress", back_populates="report",
        cascade="all, delete-orphan", passive_deletes=True,
    )
    workforce_entries = db.relationship(
        "WorkforceEntry", back_populates="report",
        cascade="all, delete-orphan", passive_deletes=True,
    )
    equipment_entries = db.relationship(
        "EquipmentEntry", back_populates="report",
        cascade="all, delete-orphan", passive_deletes=True,
    )
    observations = db.relationship(
        "SiteObservation", back_populates="report",
        cascade="all, delete-orphan", passive_deletes=True,
    )
    photos = db.relationship(
        "Photo", back_populates="report",
        cascade="all, delete-orphan", passive_deletes=True,
    )

    def adverse_weather(self, wind_threshold=None, rain_threshold=None):
        """Whether the recorded weather meets the contractual EOT thresholds.

        Returns (qualifies, reasons). Nothing is assumed: if no measurement was
        recorded the day cannot qualify, which is exactly what the Contract
        says about missing calibrated instrumentation.
        """
        reasons = []
        if (wind_threshold and self.max_wind_ms is not None
                and self.max_wind_ms > wind_threshold):
            reasons.append(f"wind {self.max_wind_ms:g} m/s exceeds {wind_threshold:g} m/s")
        if (rain_threshold and self.max_rain_mm_h is not None
                and self.max_rain_mm_h > rain_threshold):
            reasons.append(f"rainfall {self.max_rain_mm_h:g} mm/h exceeds {rain_threshold:g} mm/h")
        return bool(reasons), reasons

    @property
    def total_workers(self):
        return sum(w.workers or 0 for w in self.workforce_entries)

    @property
    def total_man_hours(self):
        return sum((w.workers or 0) * (w.hours or 0) + (w.overtime_hours or 0)
                   for w in self.workforce_entries)

    def __repr__(self):
        return f"<DailySiteReport {self.report_date}>"


class DailyProgress(db.Model):
    """One activity/workfront line of a daily report."""

    __tablename__ = "daily_progress"

    id = db.Column(db.Integer, primary_key=True)
    daily_report_id = db.Column(
        db.Integer, db.ForeignKey("daily_site_report.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    entry_date = db.Column(db.Date, nullable=False, index=True)
    wbs_code = db.Column(db.String(60), index=True)
    activity_name = db.Column(db.String(400))
    work_package = db.Column(db.String(200), index=True)
    area_id = db.Column(db.Integer, db.ForeignKey("area.id", ondelete="SET NULL"), index=True)

    planned_quantity = db.Column(db.Float, default=0.0)
    actual_quantity = db.Column(db.Float, default=0.0)
    unit = db.Column(db.String(30))
    cumulative_before = db.Column(db.Float, default=0.0)
    total_required_quantity = db.Column(db.Float)

    workers = db.Column(db.Integer, default=0)
    hours = db.Column(db.Float, default=0.0)
    comments = db.Column(db.Text)

    activity_affected = db.Column(db.Boolean, default=False, nullable=False, index=True)
    blocker_category = db.Column(db.String(40), index=True)
    blocker_description = db.Column(db.Text)
    estimated_lost_hours = db.Column(db.Float, default=0.0)

    created_at = db.Column(db.DateTime, default=_utcnow)

    report = db.relationship("DailySiteReport", back_populates="progress_entries")
    area = db.relationship("Area")

    __table_args__ = (
        Index("ix_dp_date_wbs", "entry_date", "wbs_code"),
        Index("ix_dp_date_area", "entry_date", "area_id"),
    )

    # -- deterministic calculations, all zero-division safe ----------------
    @property
    def cumulative_after(self):
        return (self.cumulative_before or 0.0) + (self.actual_quantity or 0.0)

    @property
    def achievement_pct(self):
        ratio = _safe_div(self.actual_quantity, self.planned_quantity)
        return None if ratio is None else ratio * 100.0

    @property
    def quantity_per_worker_day(self):
        return _safe_div(self.actual_quantity, self.workers)

    @property
    def quantity_per_worker_hour(self):
        if not self.workers or not self.hours:
            return None
        return _safe_div(self.actual_quantity, (self.workers or 0) * (self.hours or 0))

    @property
    def completion_pct(self):
        ratio = _safe_div(self.cumulative_after, self.total_required_quantity)
        return None if ratio is None else min(ratio * 100.0, 100.0)

    def __repr__(self):
        return f"<DailyProgress {self.entry_date} {self.wbs_code}>"


class WorkforceEntry(db.Model):
    __tablename__ = "workforce_entry"

    id = db.Column(db.Integer, primary_key=True)
    daily_report_id = db.Column(
        db.Integer, db.ForeignKey("daily_site_report.id", ondelete="CASCADE"), index=True
    )
    entry_date = db.Column(db.Date, nullable=False, index=True)
    contractor_id = db.Column(db.Integer, db.ForeignKey("contractor.id", ondelete="SET NULL"), index=True)
    contractor_name = db.Column(db.String(200))
    discipline = db.Column(db.String(60), index=True)
    work_package = db.Column(db.String(200))
    area_id = db.Column(db.Integer, db.ForeignKey("area.id", ondelete="SET NULL"), index=True)
    workers = db.Column(db.Integer, default=0)
    hours = db.Column(db.Float, default=0.0)
    overtime_hours = db.Column(db.Float, default=0.0)
    comments = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=_utcnow)

    report = db.relationship("DailySiteReport", back_populates="workforce_entries")
    contractor = db.relationship("Contractor")
    area = db.relationship("Area")

    @property
    def man_hours(self):
        return (self.workers or 0) * (self.hours or 0.0) + (self.overtime_hours or 0.0)

    def __repr__(self):
        return f"<WorkforceEntry {self.entry_date} {self.discipline} {self.workers}>"


class EquipmentEntry(db.Model):
    __tablename__ = "equipment_entry"

    id = db.Column(db.Integer, primary_key=True)
    daily_report_id = db.Column(
        db.Integer, db.ForeignKey("daily_site_report.id", ondelete="CASCADE"), index=True
    )
    entry_date = db.Column(db.Date, nullable=False, index=True)
    equipment_type = db.Column(db.String(160), nullable=False, index=True)
    contractor_id = db.Column(db.Integer, db.ForeignKey("contractor.id", ondelete="SET NULL"), index=True)
    owner = db.Column(db.String(200))
    area_id = db.Column(db.Integer, db.ForeignKey("area.id", ondelete="SET NULL"), index=True)
    quantity = db.Column(db.Integer, default=1)
    status = db.Column(db.String(30), default="WORKING", index=True)
    working_hours = db.Column(db.Float, default=0.0)
    idle_hours = db.Column(db.Float, default=0.0)
    breakdown_hours = db.Column(db.Float, default=0.0)
    reason = db.Column(db.String(300))
    comments = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=_utcnow)

    report = db.relationship("DailySiteReport", back_populates="equipment_entries")
    contractor = db.relationship("Contractor")
    area = db.relationship("Area")

    @property
    def total_hours(self):
        return (self.working_hours or 0.0) + (self.idle_hours or 0.0) + (self.breakdown_hours or 0.0)

    @property
    def utilisation_pct(self):
        total = self.total_hours
        if not total:
            return None
        return (self.working_hours or 0.0) / total * 100.0

    @property
    def lost_hours(self):
        return (self.idle_hours or 0.0) + (self.breakdown_hours or 0.0)

    def __repr__(self):
        return f"<EquipmentEntry {self.entry_date} {self.equipment_type}>"


class SiteObservation(db.Model):
    __tablename__ = "site_observation"

    id = db.Column(db.Integer, primary_key=True)
    daily_report_id = db.Column(
        db.Integer, db.ForeignKey("daily_site_report.id", ondelete="CASCADE"), index=True
    )
    entry_date = db.Column(db.Date, nullable=False, index=True)
    area_id = db.Column(db.Integer, db.ForeignKey("area.id", ondelete="SET NULL"), index=True)
    wbs_code = db.Column(db.String(60), index=True)
    observation = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(40), index=True)
    severity = db.Column(db.String(20), default="LOW", index=True)
    action_required = db.Column(db.Text)
    responsible_party = db.Column(db.String(160))
    target_date = db.Column(db.Date, index=True)
    status = db.Column(db.String(30), default="OPEN", index=True)
    closed_date = db.Column(db.Date)
    created_at = db.Column(db.DateTime, default=_utcnow)

    report = db.relationship("DailySiteReport", back_populates="observations")
    area = db.relationship("Area")
    photos = db.relationship("Photo", back_populates="observation")

    def __repr__(self):
        return f"<SiteObservation {self.entry_date} {self.category}>"


class Blocker(db.Model):
    """Lost-productivity event. Can be raised from the daily diary."""

    __tablename__ = "blocker"

    id = db.Column(db.Integer, primary_key=True)
    blocker_number = db.Column(db.String(40), unique=True, index=True)
    entry_date = db.Column(db.Date, nullable=False, index=True)
    daily_report_id = db.Column(
        db.Integer, db.ForeignKey("daily_site_report.id", ondelete="SET NULL"), index=True
    )
    wbs_code = db.Column(db.String(60), index=True)
    area_id = db.Column(db.Integer, db.ForeignKey("area.id", ondelete="SET NULL"), index=True)
    activity = db.Column(db.String(300))
    category = db.Column(db.String(40), nullable=False, index=True)
    description = db.Column(db.Text)
    start_datetime = db.Column(db.DateTime)
    end_datetime = db.Column(db.DateTime)
    estimated_lost_hours = db.Column(db.Float, default=0.0)
    actual_lost_hours = db.Column(db.Float)
    workers_affected = db.Column(db.Integer, default=0)
    equipment_affected = db.Column(db.Integer, default=0)
    responsible_party = db.Column(db.String(160))
    status = db.Column(db.String(30), default="OPEN", index=True)
    action = db.Column(db.Text)
    comments = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=_utcnow)

    area = db.relationship("Area")
    report = db.relationship("DailySiteReport")
    photos = db.relationship("Photo", back_populates="blocker")

    @property
    def effective_lost_hours(self):
        """Actual hours when recorded, otherwise the estimate."""
        if self.actual_lost_hours is not None:
            return self.actual_lost_hours
        return self.estimated_lost_hours or 0.0

    @property
    def lost_man_hours(self):
        return self.effective_lost_hours * (self.workers_affected or 0)

    def __repr__(self):
        return f"<Blocker {self.blocker_number} {self.category}>"


class Photo(db.Model):
    """Evidence photograph attached to any site record."""

    __tablename__ = "photo"

    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(300), nullable=False)
    stored_path = db.Column(db.String(500), nullable=False)
    caption = db.Column(db.String(400))
    taken_date = db.Column(db.Date, index=True)
    uploaded_at = db.Column(db.DateTime, default=_utcnow)

    daily_report_id = db.Column(
        db.Integer, db.ForeignKey("daily_site_report.id", ondelete="CASCADE"), index=True
    )
    observation_id = db.Column(
        db.Integer, db.ForeignKey("site_observation.id", ondelete="CASCADE"), index=True
    )
    quality_record_id = db.Column(
        db.Integer, db.ForeignKey("quality_record.id", ondelete="CASCADE"), index=True
    )
    blocker_id = db.Column(db.Integer, db.ForeignKey("blocker.id", ondelete="CASCADE"), index=True)
    rfi_id = db.Column(db.Integer, db.ForeignKey("rfi.id", ondelete="CASCADE"), index=True)

    report = db.relationship("DailySiteReport", back_populates="photos")
    observation = db.relationship("SiteObservation", back_populates="photos")
    quality_record = db.relationship("QualityRecord", back_populates="photos")
    blocker = db.relationship("Blocker", back_populates="photos")
    rfi = db.relationship("Rfi", back_populates="photos")

    @property
    def url_path(self):
        return f"uploads/{self.stored_path}"

    def __repr__(self):
        return f"<Photo {self.filename}>"
