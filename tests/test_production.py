"""Production hardening: CSRF, schema reconciliation, logging, health check,
commercial milestones, delay-damages exposure and adverse-weather capture.
"""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta

import pytest
from sqlalchemy import inspect, text

from app import __version__, security
from app.config import Config
from app.extensions import db
from app.models import (
    DailySiteReport,
    PaymentMilestone,
    Project,
    ScheduleVersion,
    SiteObservation,
    WbsActivity,
)
from app.services import commercial_service, importers, schema


# ==========================================================================
# Schema reconciliation
# ==========================================================================
class TestSchema:
    def test_every_model_table_exists(self, app):
        tables = set(inspect(db.engine).get_table_names())
        for table in db.metadata.sorted_tables:
            assert table.name in tables, f"{table.name} was not created"

    def test_schema_version_is_recorded(self, app):
        assert schema.current_version() == schema.SCHEMA_VERSION

    def test_reconciliation_is_idempotent(self, app):
        first = schema.ensure_schema()
        second = schema.ensure_schema()
        assert second["added_columns"] == []
        assert second["created_tables"] == []
        assert first["version"] == second["version"]

    def test_a_missing_column_is_added_back(self, app):
        # Simulate a database created by an older build by rebuilding one table
        # without a column, then letting the reconciler repair it.
        with db.engine.begin() as connection:
            connection.execute(text("DROP TABLE IF EXISTS legacy_probe"))
            connection.execute(text(
                "CREATE TABLE legacy_probe (id INTEGER PRIMARY KEY, kept TEXT)"))
            connection.execute(text("INSERT INTO legacy_probe (kept) VALUES ('data')"))

        from sqlalchemy import Column, Integer, String, Table
        probe = Table("legacy_probe", db.metadata,
                      Column("id", Integer, primary_key=True),
                      Column("kept", String(50)),
                      Column("added_later", String(50)),
                      extend_existing=True)
        try:
            schema.ensure_schema()
            columns = {c["name"] for c in inspect(db.engine).get_columns("legacy_probe")}
            assert "added_later" in columns
            with db.engine.connect() as connection:
                # The existing row survives the migration.
                assert connection.execute(
                    text("SELECT kept FROM legacy_probe")).scalar() == "data"
        finally:
            db.metadata.remove(probe)

    def test_pragmas_do_not_raise(self, app):
        schema.apply_pragmas()


# ==========================================================================
# CSRF protection
# ==========================================================================
@pytest.fixture()
def secure_app():
    """An application with CSRF enabled, as it runs in production."""
    from app import create_app

    class SecureConfig(Config):
        TESTING = True
        SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
        WTF_CSRF_ENABLED = True

    application = create_app(SecureConfig)
    with application.app_context():
        yield application
        db.session.remove()


@pytest.fixture()
def secure_client(secure_app):
    return secure_app.test_client()


class TestCsrf:
    def _token(self, client, path="/setup/project"):
        import re
        page = client.get(path).get_data(as_text=True)
        match = re.search(r'name="_csrf_token" value="([^"]+)"', page)
        return match.group(1) if match else None

    def test_post_without_a_token_is_rejected(self, secure_client):
        response = secure_client.post("/setup/project", data={"name": "Hijacked"})
        assert response.status_code == 400

    def test_post_with_a_wrong_token_is_rejected(self, secure_client):
        secure_client.get("/setup/project")
        response = secure_client.post("/setup/project",
                                      data={"name": "Hijacked", "_csrf_token": "nonsense"})
        assert response.status_code == 400

    def test_post_with_the_session_token_is_accepted(self, secure_client, secure_app):
        token = self._token(secure_client)
        assert token
        response = secure_client.post("/setup/project",
                                      data={"name": "Bassignana Solar 2",
                                            "_csrf_token": token})
        assert response.status_code in (200, 302)

    def test_the_token_is_injected_into_every_posting_form(self, secure_client):
        for path in ("/setup/project", "/daily/new", "/schedule/versions",
                     "/procurement/", "/commercial/", "/backup/"):
            page = secure_client.get(path).get_data(as_text=True)
            if "<form" not in page.lower():
                continue
            forms = page.lower().count('method="post"')
            tokens = page.count('name="_csrf_token"')
            assert tokens >= forms, f"{path}: {forms} posting form(s), {tokens} token(s)"

    def test_get_requests_are_never_blocked(self, secure_client):
        assert secure_client.get("/").status_code == 200

    def test_a_rejected_post_changes_nothing(self, secure_client, secure_app):
        before = Project.query.first().name
        secure_client.post("/setup/project", data={"name": "Hijacked"})
        assert Project.query.first().name == before

    def test_security_headers_are_set(self, secure_client):
        headers = secure_client.get("/").headers
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert headers["X-Frame-Options"] == "SAMEORIGIN"

    def test_secret_key_is_persisted_between_starts(self, tmp_path):
        first = security.load_or_create_secret_key(tmp_path)
        second = security.load_or_create_secret_key(tmp_path)
        assert first == second
        assert (tmp_path / security.SECRET_FILENAME).exists()


# ==========================================================================
# Health check
# ==========================================================================
class TestHealth:
    def test_health_endpoint_reports_ok(self, client):
        payload = client.get("/healthz").get_json()
        assert payload["status"] == "ok"
        assert payload["version"] == __version__
        assert payload["schema_version"] == schema.SCHEMA_VERSION
        assert "counts" in payload

    def test_health_reports_setup_state(self, client):
        assert client.get("/healthz").get_json()["setup_complete"] is False


# ==========================================================================
# Payment milestones
# ==========================================================================
class TestPaymentMilestones:
    @pytest.fixture()
    def priced(self, db):
        project = Project.query.first()
        project.contract_price = 4800000.0
        project.currency = "EUR"
        project.delay_lds_pct_per_day = 0.15
        project.delay_lds_cap_pct = 10.0
        project.delay_termination_days = 60
        db.session.commit()
        return project

    def _milestone(self, db, code, percentage, status="NOT STARTED", **kwargs):
        row = PaymentMilestone(milestone_code=code, description=f"Milestone {code}",
                               percentage=percentage, status=status, **kwargs)
        db.session.add(row)
        db.session.commit()
        return row

    def test_amount_is_derived_from_the_contract_price(self, app, db, priced):
        row = self._milestone(db, "PM-01", 15.0)
        assert row.amount(priced.contract_price) == pytest.approx(720000.0)

    def test_amount_is_undefined_without_a_contract_price(self, app, db):
        row = self._milestone(db, "PM-01", 15.0)
        assert row.amount(None) is None

    def test_summary_totals_and_completeness(self, app, db, priced):
        self._milestone(db, "PM-01", 15.0, "PAID")
        self._milestone(db, "PM-02", 10.0, "CERTIFIED")
        self._milestone(db, "PM-03", 75.0)
        summary = commercial_service.summary(date(2026, 9, 4))
        assert summary["total_pct"] == pytest.approx(100.0)
        assert summary["schedule_complete"] is True
        assert summary["earned_pct"] == pytest.approx(25.0)
        assert summary["paid_pct"] == pytest.approx(15.0)
        assert summary["earned_amount"] == pytest.approx(1200000.0)
        assert summary["outstanding_amount"] == pytest.approx(480000.0)

    def test_incomplete_schedule_is_flagged(self, app, db, priced):
        self._milestone(db, "PM-01", 15.0)
        assert commercial_service.summary()["schedule_complete"] is False

    def test_a_milestone_past_its_forecast_date_is_overdue(self, app, db, priced):
        self._milestone(db, "PM-01", 15.0, forecast_date=date(2026, 8, 1))
        summary = commercial_service.summary(date(2026, 9, 4))
        assert len(summary["overdue"]) == 1
        assert summary["views"][0]["derived_status"] == "OVERDUE"

    def test_an_achieved_milestone_is_not_overdue(self, app, db, priced):
        self._milestone(db, "PM-01", 15.0, "ACHIEVED", forecast_date=date(2026, 8, 1))
        assert commercial_service.summary(date(2026, 9, 4))["overdue"] == []

    def test_physical_progress_is_compared_not_conflated(self, app, db, priced,
                                                         working_version,
                                                         activity_factory):
        activity_factory(working_version, "1.1", "Work", date(2026, 8, 1), date(2026, 9, 30),
                         reported_completion_pct=10.0, duration_days=60)
        self._milestone(db, "PM-01", 15.0, "PAID")
        summary = commercial_service.summary(date(2026, 9, 4))
        assert summary["physical_pct"] == pytest.approx(10.0)
        assert summary["commercial_vs_physical"] == pytest.approx(5.0)

    def test_recording_a_state_stamps_its_date(self, app, client, db, priced):
        row = self._milestone(db, "PM-01", 15.0)
        client.post(f"/commercial/{row.id}",
                    data={"description": row.description, "percentage": "15",
                          "status": "ACHIEVED"})
        db.session.refresh(row)
        assert row.status == "ACHIEVED"
        assert row.achieved_date == date.today()

    def test_import_rejects_a_percentage_over_one_hundred(self, app):
        rows = [{"description": "Bad milestone", "percentage": "150"}]
        result = importers.validate("payments", rows, {})
        assert result["rows"][0]["action"] == "ERROR"

    def test_prepared_payment_file_totals_one_hundred(self, app):
        from pathlib import Path
        path = (Path(__file__).resolve().parent.parent / "project_data" /
                "import_ready" / "payments_Schedule10.csv")
        if not path.exists():
            pytest.skip("prepared Bassignana files are not present")
        _, rows = importers.read_rows(path)
        result = importers.validate("payments", rows, {})
        assert result["summary"]["error"] == 0
        total = sum(r["data"]["percentage"] for r in result["rows"])
        assert total == pytest.approx(100.0)


# ==========================================================================
# Delay liquidated damages exposure
# ==========================================================================
class TestDelayDamages:
    @pytest.fixture()
    def contracted(self, db, baseline_version, working_version, activity_factory):
        project = Project.query.first()
        project.contract_price = 4800000.0
        project.delay_lds_pct_per_day = 0.15
        project.delay_lds_cap_pct = 10.0
        project.delay_termination_days = 60
        db.session.commit()
        activity_factory(baseline_version, "1.6.3.2",
                         "PV PLANT PROVISIONAL ACCEPTANCE CERTIFICATE",
                         date(2027, 1, 22), date(2027, 1, 22), is_milestone=True)
        activity_factory(working_version, "1.6.4.2",
                         "PV PLANT PROVISIONAL ACCEPTANCE CERTIFICATE",
                         date(2027, 3, 1), date(2027, 3, 1), is_milestone=True)
        return project

    def test_exposure_uses_the_contractual_rate(self, app, contracted):
        exposure = commercial_service.delay_damages_exposure(date(2026, 9, 4))
        assert exposure["scheduled_pac"] == date(2027, 1, 22)
        assert exposure["forecast_pac"] == date(2027, 3, 1)
        assert exposure["slip_days"] == 38
        assert exposure["daily_rate"] == pytest.approx(7200.0)
        assert exposure["exposure"] == pytest.approx(273600.0)
        assert exposure["capped"] is False

    def test_exposure_is_capped(self, app, db, contracted, working_version,
                                activity_factory):
        activity = WbsActivity.query.filter_by(
            schedule_version_id=working_version.id, wbs_code="1.6.4.2").one()
        activity.plan_finish = date(2027, 6, 30)
        db.session.commit()
        exposure = commercial_service.delay_damages_exposure(date(2026, 9, 4))
        assert exposure["capped"] is True
        assert exposure["exposure"] == pytest.approx(480000.0)
        assert exposure["termination_risk"] is True

    def test_no_exposure_when_ahead_of_the_baseline(self, app, db, contracted,
                                                   working_version):
        activity = WbsActivity.query.filter_by(
            schedule_version_id=working_version.id, wbs_code="1.6.4.2").one()
        activity.plan_finish = date(2027, 1, 10)
        db.session.commit()
        exposure = commercial_service.delay_damages_exposure(date(2026, 9, 4))
        assert exposure["slip_days"] < 0
        assert exposure["exposure"] is None

    def test_nothing_is_reported_without_the_contract_parameters(self, app, db,
                                                                 baseline_version):
        assert commercial_service.delay_damages_exposure() is None


# ==========================================================================
# Adverse weather
# ==========================================================================
class TestAdverseWeather:
    def _report(self, db, **kwargs):
        row = DailySiteReport(report_date=date(2026, 9, 4), report_number="BAS-DSR-0001",
                              **kwargs)
        db.session.add(row)
        db.session.commit()
        return row

    def test_wind_above_the_threshold_qualifies(self, app, db):
        report = self._report(db, max_wind_ms=32.0)
        qualifies, reasons = report.adverse_weather(30.0, 10.0)
        assert qualifies is True
        assert "wind 32 m/s exceeds 30 m/s" in reasons[0]

    def test_rainfall_above_the_threshold_qualifies(self, app, db):
        report = self._report(db, max_rain_mm_h=12.5)
        qualifies, reasons = report.adverse_weather(30.0, 10.0)
        assert qualifies is True
        assert "rainfall" in reasons[0]

    def test_a_measurement_at_the_threshold_does_not_qualify(self, app, db):
        report = self._report(db, max_wind_ms=30.0, max_rain_mm_h=10.0)
        assert report.adverse_weather(30.0, 10.0)[0] is False

    def test_a_missing_measurement_can_never_qualify(self, app, db):
        # The Contract deems entitlement waived without calibrated instrumentation,
        # so an unmeasured day must not qualify on assumption.
        report = self._report(db, adverse_weather_claimed=True)
        assert report.adverse_weather(30.0, 10.0)[0] is False

    def test_no_thresholds_registered_means_no_qualification(self, app, db):
        report = self._report(db, max_wind_ms=99.0)
        assert report.adverse_weather(None, None)[0] is False

    def test_the_diary_records_the_measurements(self, app, client, db):
        client.post("/daily/new", data={"report_date": "2026-09-04",
                                        "max_wind_ms": "31.5", "max_rain_mm_h": "4",
                                        "adverse_weather_claimed": "1"})
        report = DailySiteReport.query.one()
        assert report.max_wind_ms == pytest.approx(31.5)
        assert report.max_rain_mm_h == pytest.approx(4.0)
        assert report.adverse_weather_claimed is True


# ==========================================================================
# Observation backlog import
# ==========================================================================
class TestObservationImport:
    def test_observations_import_and_link_to_an_area(self, app, db, area):
        rows = [{"observation_date": "2026-08-27", "area_code": area.area_code,
                 "observation": "Culvert undersized", "category": "Drainage",
                 "severity": "HIGH", "action_required": "Replace with a larger culvert",
                 "responsible_party": "TOZZI SUD SpA", "status": "OPEN"}]
        importers.commit("observations", importers.validate("observations", rows, {}), {})
        row = SiteObservation.query.one()
        assert row.entry_date == date(2026, 8, 27)
        assert row.area_id == area.id
        assert row.severity == "HIGH"

    def test_an_unknown_area_is_rejected(self, app):
        rows = [{"observation_date": "2026-08-27", "observation": "x",
                 "area_code": "NOWHERE"}]
        result = importers.validate("observations", rows, {})
        assert result["rows"][0]["action"] == "ERROR"

    def test_a_missing_date_is_rejected(self, app):
        result = importers.validate("observations", [{"observation": "x"}], {})
        assert result["rows"][0]["action"] == "ERROR"

    def test_an_unknown_category_falls_back_with_a_warning(self, app):
        rows = [{"observation_date": "2026-08-27", "observation": "x",
                 "category": "Nonsense"}]
        result = importers.validate("observations", rows, {})
        assert result["rows"][0]["data"]["category"] == "Other"
        assert result["rows"][0]["warnings"]

    def test_reimporting_the_same_observation_updates_it(self, app, db):
        rows = [{"observation_date": "2026-08-27", "observation": "Same text",
                 "severity": "LOW"}]
        importers.commit("observations", importers.validate("observations", rows, {}), {})
        rows[0]["severity"] = "HIGH"
        result = importers.validate("observations", rows, {})
        assert result["summary"]["update"] == 1
        importers.commit("observations", result, {})
        assert SiteObservation.query.count() == 1
        assert SiteObservation.query.one().severity == "HIGH"


# ==========================================================================
# Import workspace housekeeping
# ==========================================================================
class TestImportHousekeeping:
    def test_stale_uploads_are_purged(self, app, tmp_path):
        workspace = importers.import_workspace()
        stale = workspace / "abc__old.csv"
        stale.write_text("a,b\n", encoding="utf-8")
        import os
        import time
        old = time.time() - 60 * 60 * 48
        os.utime(stale, (old, old))
        removed = importers.purge_stale_uploads()
        assert removed >= 1
        assert not stale.exists()

    def test_recent_uploads_are_kept(self, app):
        workspace = importers.import_workspace()
        fresh = workspace / "def__new.csv"
        fresh.write_text("a,b\n", encoding="utf-8")
        importers.purge_stale_uploads()
        assert fresh.exists()
        fresh.unlink()


# ==========================================================================
# Prepared Bassignana files recovered in the second pass
# ==========================================================================
class TestRecoveredSourceData:
    @pytest.fixture()
    def ready(self):
        from pathlib import Path
        directory = (Path(__file__).resolve().parent.parent / "project_data" /
                     "import_ready")
        if not directory.exists():
            pytest.skip("prepared Bassignana files are not present")
        return directory

    @pytest.mark.parametrize("filename,key", [
        ("areas_Schedule13B_layout.csv", "areas"),
        ("quantities_boq_Schedule01_13B_IFC.csv", "quantities"),
        ("quality_itp_Schedule02_technical.csv", "quality"),
        ("documents_Schedule06_executive_design.csv", "documents"),
        ("observations_2026-08-27_site_report.csv", "observations"),
        ("payments_Schedule10.csv", "payments"),
    ])
    def test_each_prepared_file_validates(self, app, ready, filename, key):
        path = ready / filename
        if not path.exists():
            pytest.skip(f"{filename} is not present")
        _, rows = importers.read_rows(path)
        if key in {"quantities", "observations"}:
            # These files allocate rows to workfronts, so the area register has
            # to exist first -- which is exactly what the validator enforces.
            area_path = ready / "areas_Schedule13B_layout.csv"
            _, area_rows = importers.read_rows(area_path)
            importers.commit("areas", importers.validate("areas", area_rows, {}), {})
        result = importers.validate(key, rows, {})
        assert result["summary"]["error"] == 0, [
            r["errors"] for r in result["rows"] if r["errors"]][:3]

    def test_the_area_register_carries_the_scope_boundary(self, app, ready):
        path = ready / "areas_Schedule13B_layout.csv"
        if not path.exists():
            pytest.skip("prepared Bassignana files are not present")
        _, rows = importers.read_rows(path)
        codes = {r["area_code"] for r in rows}
        # The three transformer substations named in Schedule 13B rev.2.
        assert {"CT1", "CT2", "CT3"} <= codes
        delivery_cabin = next(r for r in rows if r["area_code"] == "CC")
        assert "EXCLUDED" in delivery_cabin["description"]

    def test_the_boq_records_the_superseded_transformer_count(self, app, ready):
        path = ready / "quantities_boq_Schedule01_13B_IFC.csv"
        if not path.exists():
            pytest.skip("prepared Bassignana files are not present")
        _, rows = importers.read_rows(path)
        substations = next(r for r in rows if "CT1" in r["item"])
        assert substations["total_quantity"] == "3"
        assert "SUPERSEDES Schedule 01" in substations["notes"]

    def test_source_conflicts_are_flagged_not_resolved_silently(self, app, ready):
        path = ready / "quantities_boq_Schedule01_13B_IFC.csv"
        if not path.exists():
            pytest.skip("prepared Bassignana files are not present")
        _, rows = importers.read_rows(path)
        flagged = [r for r in rows if "RECONCILIATION REQUIRED" in (r["notes"] or "")]
        assert flagged, "the inverter rating conflict must stay visible"
