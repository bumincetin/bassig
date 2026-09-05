"""Daily report, weekly report, CSV exports, backup and the web surface."""
from __future__ import annotations

import csv
import io
import sqlite3
from datetime import date, timedelta

import pytest

from app import constants as C
from app.models import (
    Blocker,
    DailyProgress,
    DailySiteReport,
    EquipmentEntry,
    Project,
    QualityRecord,
    SiteObservation,
    WorkforceEntry,
)
from app.services import backup, exporters, numbering, reports


@pytest.fixture()
def populated_day(db, daily_report, area, working_version, activity_factory, today):
    activity_factory(working_version, "1.3.2.2", "Foundation Piles Ramming",
                     today - timedelta(days=10), today + timedelta(days=20),
                     work_package="PV Mechanical Works", discipline="Mechanical",
                     progress_method="QUANTITY", total_required_quantity=1000.0, unit="no")
    db.session.add_all([
        DailyProgress(daily_report_id=daily_report.id, entry_date=today,
                      wbs_code="1.3.2.2", activity_name="Foundation Piles Ramming",
                      work_package="PV Mechanical Works", area_id=area.id,
                      planned_quantity=60, actual_quantity=45, unit="no",
                      total_required_quantity=1000.0, workers=9, hours=10,
                      activity_affected=True, blocker_category="Material",
                      estimated_lost_hours=3.0),
        WorkforceEntry(daily_report_id=daily_report.id, entry_date=today,
                       contractor_name="TOZZI SUD SpA", discipline="Mechanical",
                       area_id=area.id, workers=9, hours=10, overtime_hours=4),
        WorkforceEntry(daily_report_id=daily_report.id, entry_date=today,
                       contractor_name="Subcontractor Srl", discipline="Civil",
                       workers=5, hours=8),
        EquipmentEntry(daily_report_id=daily_report.id, entry_date=today,
                       equipment_type="Pile driving rig", quantity=2, status="WORKING",
                       working_hours=8, idle_hours=1, breakdown_hours=1),
        SiteObservation(daily_report_id=daily_report.id, entry_date=today, area_id=area.id,
                        observation="Standing water at the north drainage channel",
                        category="Drainage", severity="HIGH", status="OPEN",
                        target_date=today + timedelta(days=3)),
        Blocker(blocker_number="BAS-BLK-0001", entry_date=today, category="Material",
                description="Pile delivery delayed", estimated_lost_hours=3.0,
                workers_affected=9, status="OPEN", wbs_code="1.3.2.2"),
        QualityRecord(record_number="BAS-NCR-0001", record_type="NCR", record_date=today,
                      title="Pile verticality out of tolerance", status="OPEN",
                      target_closure_date=today - timedelta(days=2)),
    ])
    db.session.commit()
    return daily_report


class TestDailyReport:
    def test_report_assembles_every_section(self, app, populated_day, today):
        data = reports.daily_report(today)
        assert data["report"] is not None
        assert len(data["progress_rows"]) == 1
        assert len(data["workforce_rows"]) == 2
        assert len(data["equipment_rows"]) == 1
        assert len(data["observation_rows"]) == 1
        assert len(data["blocker_rows"]) == 1

    def test_totals_are_counted_not_estimated(self, app, populated_day, today):
        data = reports.daily_report(today)
        assert data["planned_quantity"] == pytest.approx(60.0)
        assert data["actual_quantity"] == pytest.approx(45.0)
        assert data["achievement"] == pytest.approx(75.0)
        assert data["total_workers"] == 14
        assert data["total_man_hours"] == pytest.approx(9 * 10 + 4 + 5 * 8)
        assert data["lost_hours"] == pytest.approx(3.0)

    def test_summary_is_deterministic_counted_facts(self, app, populated_day, today):
        summary = reports.daily_report(today)["summary"]
        assert any("Active workfronts reporting progress: 1" in line for line in summary)
        assert any("Daily achievement: 75.0%" in line for line in summary)
        assert any("Activities below the daily target: 1 of 1" in line for line in summary)
        assert any("Largest cause of lost hours today: Material" in line for line in summary)

    def test_summary_states_when_achievement_is_not_calculable(self, app, db, today):
        report = DailySiteReport(report_date=today, report_number="BAS-DSR-0002")
        db.session.add(report)
        db.session.flush()
        db.session.add(DailyProgress(daily_report_id=report.id, entry_date=today,
                                     wbs_code="1.1", planned_quantity=0, actual_quantity=10))
        db.session.commit()
        summary = reports.daily_report(today)["summary"]
        assert any("no planned quantity was recorded" in line for line in summary)

    def test_report_for_a_day_with_no_diary_still_renders(self, app, today):
        data = reports.daily_report(today + timedelta(days=1))
        assert data["report"] is None
        assert data["progress_rows"] == []
        assert data["summary"]

    def test_overdue_quality_is_listed(self, app, populated_day, today):
        data = reports.daily_report(today)
        assert len(data["overdue_quality"]) == 1


class TestWeeklyReport:
    def test_week_bounds_are_monday_to_sunday(self, app):
        start, end = reports.week_bounds(date(2026, 9, 4))
        assert start == date(2026, 8, 31)
        assert end == date(2026, 9, 6)
        assert start.weekday() == 0 and end.weekday() == 6

    def test_weekly_totals(self, app, populated_day, today):
        data = reports.weekly_report(today)
        assert data["week_planned"] == pytest.approx(60.0)
        assert data["week_actual"] == pytest.approx(45.0)
        assert data["week_achievement"] == pytest.approx(75.0)
        assert data["reports_filed"] == 1

    def test_weekly_report_lists_top_actions(self, app, populated_day, today):
        actions = reports.weekly_report(today)["actions"]
        assert any("BAS-NCR-0001" in action for action in actions)

    def test_weekly_report_includes_acceptance_readiness(self, app, populated_day, today):
        data = reports.weekly_report(today)
        assert len(data["acceptance"]["gates"]) == 4

    def test_weekly_report_carries_the_workforce_peak(self, app, populated_day, today):
        assert reports.weekly_report(today)["workforce_peak"] == 14


class TestExports:
    def _parse(self, text):
        return list(csv.reader(io.StringIO(text)))

    def test_every_export_produces_a_header(self, app):
        for key, (label, function) in exporters.EXPORTS.items():
            filename, text = function()
            assert filename.startswith("bassignana_")
            assert filename.endswith(".csv")
            rows = self._parse(text)
            assert rows and rows[0], f"{key} produced no header"

    def test_daily_progress_export_contains_the_records(self, app, populated_day, today):
        _, text = exporters.export_daily_progress()
        rows = self._parse(text)
        assert len(rows) == 2
        assert "Foundation Piles Ramming" in rows[1]

    def test_daily_progress_export_respects_the_date_filter(self, app, populated_day, today):
        _, text = exporters.export_daily_progress(date_from=today + timedelta(days=1))
        assert len(self._parse(text)) == 1

    def test_schedule_export_carries_the_control_columns(self, app, baseline_version,
                                                         working_version, activity_factory,
                                                         today):
        activity_factory(baseline_version, "1.1", "Activity", date(2026, 5, 1), date(2026, 5, 31))
        activity_factory(working_version, "1.1", "Activity", date(2026, 6, 1), date(2026, 6, 30))
        _, text = exporters.export_schedule(as_of=today)
        rows = self._parse(text)
        assert "Variance (pp)" in rows[0]
        assert "Baseline start" in rows[0]
        assert "Classification" in rows[0]
        assert len(rows) == 2

    def test_blocker_export_includes_lost_man_hours(self, app, populated_day):
        _, text = exporters.export_blockers()
        rows = self._parse(text)
        assert "Lost man-hours" in rows[0]
        assert rows[1][0] == "BAS-BLK-0001"

    def test_materials_export_keeps_delivered_accepted_installed_separate(self, app):
        _, text = exporters.export_materials()
        header = self._parse(text)[0]
        for column in ("Delivered", "Accepted", "Installed", "Available stock"):
            assert column in header

    def test_export_values_are_iso_dates(self, app, populated_day, today):
        _, text = exporters.export_daily_progress()
        assert self._parse(text)[1][0] == today.isoformat()


class TestBackup:
    def test_backup_creates_a_timestamped_file(self, app, tmp_path, monkeypatch):
        source = tmp_path / "bassignana.db"
        with sqlite3.connect(str(source)) as conn:
            conn.execute("CREATE TABLE t (a INTEGER)")
            conn.execute("INSERT INTO t VALUES (1)")
        monkeypatch.setitem(app.config, "SQLALCHEMY_DATABASE_URI", f"sqlite:///{source.as_posix()}")
        monkeypatch.setitem(app.config, "BACKUP_DIR", tmp_path / "backups")
        created = backup.create_backup()
        assert created.exists()
        assert created.name.startswith("bassignana_")
        assert created.name.endswith(".db")

    def test_backup_passes_its_integrity_check(self, app, tmp_path, monkeypatch):
        source = tmp_path / "bassignana.db"
        with sqlite3.connect(str(source)) as conn:
            conn.execute("CREATE TABLE t (a INTEGER)")
        monkeypatch.setitem(app.config, "SQLALCHEMY_DATABASE_URI", f"sqlite:///{source.as_posix()}")
        monkeypatch.setitem(app.config, "BACKUP_DIR", tmp_path / "backups")
        created = backup.create_backup()
        ok, detail = backup.verify_backup(created)
        assert ok is True
        assert "integrity_check=ok" in detail

    def test_backup_preserves_the_data(self, app, tmp_path, monkeypatch):
        source = tmp_path / "bassignana.db"
        with sqlite3.connect(str(source)) as conn:
            conn.execute("CREATE TABLE t (a INTEGER)")
            conn.execute("INSERT INTO t VALUES (42)")
        monkeypatch.setitem(app.config, "SQLALCHEMY_DATABASE_URI", f"sqlite:///{source.as_posix()}")
        monkeypatch.setitem(app.config, "BACKUP_DIR", tmp_path / "backups")
        created = backup.create_backup()
        with sqlite3.connect(str(created)) as conn:
            assert conn.execute("SELECT a FROM t").fetchone()[0] == 42

    def test_a_corrupt_file_fails_verification(self, app, tmp_path):
        broken = tmp_path / "broken.db"
        broken.write_bytes(b"this is not a database")
        ok, _ = backup.verify_backup(broken)
        assert ok is False

    def test_missing_file_fails_verification(self, app, tmp_path):
        ok, detail = backup.verify_backup(tmp_path / "absent.db")
        assert ok is False
        assert "not found" in detail.lower()

    def test_restore_instructions_mention_uploads(self, app):
        joined = " ".join(backup.RESTORE_INSTRUCTIONS)
        assert "static/uploads/" in joined
        assert "project_data/source_documents/" in joined


class TestWebSurface:
    def test_dashboard_renders(self, app, client):
        response = client.get("/")
        assert response.status_code == 200
        assert b"BASSIGNANA EPC CONTROL" in response.data

    def test_dashboard_shows_data_required_before_setup(self, app, client):
        assert b"DATA REQUIRED" in client.get("/").data

    def test_dashboard_chart_payload_is_json(self, app, client):
        payload = client.get("/dashboard/charts.json").get_json()
        for key in ("progress_curve", "by_work_package", "lost_hours", "acceptance"):
            assert key in payload

    def test_daily_report_page_renders(self, app, client, populated_day, today):
        response = client.get(f"/reports/daily?date={today.isoformat()}")
        assert response.status_code == 200
        assert b"DAILY SITE REPORT" in response.data
        assert b"Foundation Piles Ramming" in response.data

    def test_weekly_report_page_renders(self, app, client, populated_day, today):
        response = client.get(f"/reports/weekly?week={today.isoformat()}")
        assert response.status_code == 200
        assert b"WEEKLY PROJECT CONTROL REPORT" in response.data

    def test_csv_export_route_sets_a_download_header(self, app, client):
        response = client.get("/data/export/schedule.csv")
        assert response.status_code == 200
        assert "attachment" in response.headers["Content-Disposition"]

    def test_setup_cannot_be_completed_with_missing_data(self, app, client):
        response = client.post("/setup/complete", follow_redirects=True)
        assert b"cannot be marked complete" in response.data
        assert Project.query.first().setup_complete is False

    def test_a_daily_report_can_be_created_and_a_blocker_raised_from_it(
            self, app, client, db, today, working_version, activity_factory):
        activity_factory(working_version, "1.3.2.2", "Foundation Piles Ramming",
                         today, today + timedelta(days=20))
        client.post("/daily/new", data={"report_date": today.isoformat(),
                                        "prepared_by": "Site Manager", "shift": "DAY"})
        report = DailySiteReport.query.filter_by(report_date=today).one()
        client.post(f"/daily/{report.id}/progress", data={
            "wbs_code": "1.3.2.2", "planned_quantity": "60", "actual_quantity": "45",
            "workers": "9", "hours": "10", "activity_affected": "1",
            "blocker_category": "Material", "estimated_lost_hours": "3",
            "blocker_description": "Pile delivery delayed"})
        entry = DailyProgress.query.one()
        assert entry.achievement_pct == pytest.approx(75.0)
        raised = Blocker.query.one()
        assert raised.category == "Material"
        assert raised.blocker_number == "BAS-BLK-0001"

    def test_a_gate_cannot_be_accepted_without_naming_who_accepted_it(
            self, app, client, db):
        response = client.post("/acceptance/gate/A", data={"status": "ACCEPTED"},
                               follow_redirects=True)
        assert b"Record who accepted the gate" in response.data
        from app.models import AcceptanceGate
        assert AcceptanceGate.query.filter_by(gate_code="A").one().status == "NOT STARTED"

    def test_punch_and_ncr_reclassification_is_explicit_and_renumbers(
            self, app, client, db, today):
        record = QualityRecord(record_number="BAS-PUN-0001", record_type="PUNCH LIST",
                               record_date=today, title="Trench not reinstated", status="OPEN")
        db.session.add(record)
        db.session.commit()
        client.post(f"/issues/quality/{record.id}/reclassify", data={"record_type": "NCR"})
        db.session.refresh(record)
        assert record.record_type == "NCR"
        assert record.record_number == "BAS-NCR-0001"
        assert "Reclassified from PUNCH LIST" in record.comments
