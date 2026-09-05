"""Shared pytest fixtures.

Every test runs against a fresh in-memory database, so no test can touch the
live Bassignana data in data/bassignana.db.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from app import create_app
from app.config import TestConfig
from app.extensions import db as _db
from app.models import (
    AcceptanceGate,
    AcceptanceGateItem,
    Area,
    Blocker,
    Contractor,
    DailyProgress,
    DailySiteReport,
    Delivery,
    EquipmentEntry,
    Material,
    MaterialTransaction,
    ProcurementPackage,
    Project,
    QualityRecord,
    Rfi,
    ScheduleVersion,
    SourceDocument,
    WbsActivity,
    WorkforceEntry,
)


@pytest.fixture()
def app():
    application = create_app(TestConfig)
    with application.app_context():
        yield application
        _db.session.remove()


@pytest.fixture()
def db(app):
    return _db


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def today():
    return date(2026, 9, 4)


# --------------------------------------------------------------------------
# Builders
# --------------------------------------------------------------------------
@pytest.fixture()
def baseline_version(db):
    document = SourceDocument(
        document_type="PROGRAMME / SCHEDULE",
        title="Schedule 03 - Project Timeline",
        revision="18.05.2026",
        status="CONTRACTUAL BASELINE",
        contractual=True,
    )
    db.session.add(document)
    db.session.flush()
    version = ScheduleVersion(
        name="Schedule 03 - Project Timeline",
        revision="18.05.2026",
        schedule_type="CONTRACTUAL BASELINE",
        effective_date=date(2026, 5, 18),
        is_contractual_baseline=True,
        locked=True,
        source_document_id=document.id,
    )
    db.session.add(version)
    db.session.commit()
    return version


@pytest.fixture()
def working_version(db):
    document = SourceDocument(
        document_type="PROGRAMME / SCHEDULE",
        title="Schedule 03 - Project timeline (27.07.2026)",
        revision="27.07.2026",
        status="CURRENT WORKING",
    )
    db.session.add(document)
    db.session.flush()
    version = ScheduleVersion(
        name="Schedule 03 update",
        revision="27.07.2026",
        schedule_type="CURRENT WORKING",
        effective_date=date(2026, 7, 27),
        is_current_working=True,
        source_document_id=document.id,
    )
    db.session.add(version)
    db.session.commit()
    return version


def make_activity(db, version, wbs_code, name, start, finish, **kwargs):
    kwargs.setdefault("duration_days", (finish - start).days)
    activity = WbsActivity(
        schedule_version_id=version.id,
        wbs_code=wbs_code,
        parent_wbs_code=wbs_code.rsplit(".", 1)[0] if "." in wbs_code else None,
        activity_name=name,
        level=wbs_code.count(".") + 1,
        plan_start=start,
        plan_finish=finish,
        **kwargs,
    )
    if version.is_contractual_baseline:
        activity.baseline_start = kwargs.get("baseline_start", start)
        activity.baseline_finish = kwargs.get("baseline_finish", finish)
    db.session.add(activity)
    db.session.commit()
    return activity


@pytest.fixture()
def activity_factory(db):
    def factory(version, wbs_code, name, start, finish, **kwargs):
        return make_activity(db, version, wbs_code, name, start, finish, **kwargs)
    return factory


@pytest.fixture()
def area(db):
    row = Area(area_code="TEST-A", area_name="Test workfront",
               drawing_reference="26C009-2C020")
    db.session.add(row)
    db.session.commit()
    return row


@pytest.fixture()
def daily_report(db, today):
    report = DailySiteReport(report_date=today, report_number="BAS-DSR-0001",
                             weather="Clear", shift="DAY", prepared_by="Site Manager")
    db.session.add(report)
    db.session.commit()
    return report


@pytest.fixture()
def gate_a(db):
    return AcceptanceGate.query.filter_by(gate_code="A").first()
