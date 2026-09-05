"""Weighted project progress, quantity progress and production-rate forecasting."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from app import constants as C
from app.models import DailyProgress, DailySiteReport
from app.services import forecasting, progress, settings


def add_progress(db, report, wbs_code, day, planned, actual, workers=8, hours=10, unit="no"):
    entry = DailyProgress(
        daily_report_id=report.id, entry_date=day, wbs_code=wbs_code,
        planned_quantity=planned, actual_quantity=actual, unit=unit,
        workers=workers, hours=hours,
    )
    db.session.add(entry)
    db.session.commit()
    return entry


class TestWeightedRollup:
    def test_rollup_is_weighted_not_averaged(
            self, app, db, working_version, activity_factory, today):
        activity_factory(working_version, "1.1", "Long activity",
                         today - timedelta(days=90), today,
                         reported_completion_pct=10.0, duration_days=90)
        activity_factory(working_version, "1.2", "Short activity",
                         today - timedelta(days=10), today,
                         reported_completion_pct=100.0, duration_days=10)
        result = progress.rollup(working_version, today)
        assert result["overall_actual"] == pytest.approx(19.0)
        assert result["overall_actual"] != pytest.approx(55.0)

    def test_summary_rows_are_excluded_from_the_rollup(
            self, app, db, working_version, activity_factory, today):
        activity_factory(working_version, "1", "Project summary",
                         today - timedelta(days=90), today,
                         reported_completion_pct=100.0, duration_days=90)
        activity_factory(working_version, "1.1", "Leaf one",
                         today - timedelta(days=10), today,
                         reported_completion_pct=0.0, duration_days=10)
        result = progress.rollup(working_version, today)
        # Only the leaf counts, so the summary's 100% must not leak into the total.
        assert result["leaf_count"] == 1
        assert result["overall_actual"] == pytest.approx(0.0)

    def test_project_progress_never_exceeds_one_hundred(
            self, app, db, working_version, activity_factory, today):
        activity_factory(working_version, "1.1", "Over-reported",
                         today - timedelta(days=10), today,
                         reported_completion_pct=100.0, duration_days=10)
        assert progress.rollup(working_version, today)["overall_actual"] <= 100.0

    def test_approved_weight_basis_ignores_unweighted_activities(
            self, app, db, working_version, activity_factory, today):
        activity_factory(working_version, "1.1", "Weighted", today - timedelta(days=10), today,
                         reported_completion_pct=50.0, duration_days=10,
                         progress_weight=100.0, weight_basis="APPROVED WEIGHT")
        activity_factory(working_version, "1.2", "Unweighted", today - timedelta(days=10), today,
                         reported_completion_pct=0.0, duration_days=10)
        settings.set_value("progress_weight_basis", "APPROVED WEIGHT")
        db.session.commit()
        assert progress.rollup(working_version, today)["overall_actual"] == pytest.approx(50.0)

    def test_weighting_basis_report_warns_when_weights_are_not_approved(
            self, app, db, working_version):
        report = progress.weighting_basis_report()
        assert report["is_approved"] is False
        assert C.DATA_REQUIRED in report["warning"]

    def test_weighting_basis_report_is_clean_with_approved_weights(
            self, app, db, working_version, activity_factory, today):
        activity_factory(working_version, "1.1", "Weighted", today - timedelta(days=10), today,
                         progress_weight=10.0, weight_basis="APPROVED WEIGHT")
        settings.set_value("progress_weight_basis", "APPROVED WEIGHT")
        db.session.commit()
        report = progress.weighting_basis_report()
        assert report["is_approved"] is True
        assert report["warning"] is None

    def test_milestones_keep_a_nominal_weight(
            self, app, db, working_version, activity_factory, today):
        milestone = activity_factory(working_version, "1.1", "Milestone", today, today,
                                     is_milestone=True, duration_days=0)
        assert progress.activity_weight(milestone, "DURATION DERIVED") == 1.0


class TestQuantityProgress:
    def test_quantity_activity_progress_comes_from_daily_records(
            self, app, db, working_version, activity_factory, daily_report, today):
        activity = activity_factory(
            working_version, "1.3.2.4", "PV Modules Installation",
            today - timedelta(days=10), today + timedelta(days=20),
            progress_method="QUANTITY", total_required_quantity=13965.0, unit="no")
        add_progress(db, daily_report, "1.3.2.4", today, 500, 1396.5)
        percent, basis = progress.activity_actual_pct(
            activity, progress.completed_quantity_by_wbs(today))
        assert basis == "QUANTITY"
        assert percent == pytest.approx(10.0)

    def test_quantity_activity_without_a_total_reports_data_required(
            self, app, db, working_version, activity_factory, today):
        activity = activity_factory(working_version, "1.3.2.4", "PV Modules Installation",
                                    today, today + timedelta(days=10),
                                    progress_method="QUANTITY")
        percent, basis = progress.activity_actual_pct(activity, {})
        assert percent is None
        assert basis == C.DATA_REQUIRED

    def test_manual_percentage_is_labelled_manual(
            self, app, db, working_version, activity_factory, today):
        activity = activity_factory(working_version, "1.1", "Design", today, today,
                                    reported_completion_pct=42.0)
        percent, basis = progress.activity_actual_pct(activity, {})
        assert percent == pytest.approx(42.0)
        assert basis == "MANUAL"
        assert activity.manual_pct is True

    def test_quantity_progress_cannot_exceed_one_hundred(
            self, app, db, working_version, activity_factory, daily_report, today):
        activity = activity_factory(working_version, "1.1", "Piles", today, today,
                                    progress_method="QUANTITY", total_required_quantity=100.0)
        add_progress(db, daily_report, "1.1", today, 100, 250)
        percent, _ = progress.activity_actual_pct(
            activity, progress.completed_quantity_by_wbs(today))
        assert percent == pytest.approx(100.0)


class TestContractualPlanned:
    def test_contractual_planned_uses_baseline_dates(
            self, app, db, baseline_version, activity_factory):
        activity_factory(baseline_version, "1.1", "Activity",
                         date(2026, 5, 1), date(2026, 5, 31), duration_days=30)
        value = progress.contractual_planned_pct(date(2026, 5, 16))
        assert value == pytest.approx(50.0)

    def test_no_baseline_gives_no_contractual_planned(self, app, db, working_version):
        assert progress.contractual_planned_pct(date(2026, 5, 16)) is None


class TestForecast:
    @pytest.fixture()
    def piling(self, db, working_version, activity_factory, today):
        return activity_factory(
            working_version, "1.3.2.2", "Foundation Piles Ramming",
            today - timedelta(days=10), today + timedelta(days=20),
            progress_method="QUANTITY", total_required_quantity=1000.0, unit="no")

    def _record(self, db, wbs, day, quantity):
        report = DailySiteReport.query.filter_by(report_date=day).first()
        if report is None:
            report = DailySiteReport(report_date=day, report_number=f"BAS-DSR-{day:%m%d}")
            db.session.add(report)
            db.session.flush()
        db.session.add(DailyProgress(daily_report_id=report.id, entry_date=day,
                                     wbs_code=wbs, planned_quantity=quantity,
                                     actual_quantity=quantity, workers=8, hours=10))
        db.session.commit()

    def test_forecast_reports_insufficient_history(self, app, db, piling, today):
        self._record(db, "1.3.2.2", today, 50)
        result = forecasting.forecast_for_activity(piling, today, window_days=7)
        assert result["message"] == forecasting.INSUFFICIENT
        assert result["forecast_finish"] is None

    def test_forecast_computes_rate_and_finish(self, app, db, piling, today):
        for offset, quantity in enumerate([50, 60, 40, 50, 50]):
            self._record(db, "1.3.2.2", today - timedelta(days=offset), quantity)
        result = forecasting.forecast_for_activity(piling, today, window_days=7)
        assert result["active_days"] == 5
        assert result["rate"] == pytest.approx(50.0)
        assert result["completed"] == pytest.approx(250.0)
        assert result["remaining"] == pytest.approx(750.0)
        assert result["working_days_remaining"] == pytest.approx(15.0)
        assert result["forecast_finish"] is not None
        assert result["message"] is None
        assert result["label"] == "Simple production-rate forecast"

    def test_idle_days_do_not_deflate_the_rate(self, app, db, piling, today):
        self._record(db, "1.3.2.2", today, 100)
        self._record(db, "1.3.2.2", today - timedelta(days=1), 0)
        self._record(db, "1.3.2.2", today - timedelta(days=2), 100)
        self._record(db, "1.3.2.2", today - timedelta(days=3), 100)
        result = forecasting.forecast_for_activity(piling, today, window_days=7)
        assert result["rate"] == pytest.approx(100.0)
        assert result["active_days"] == 3

    def test_forecast_without_a_total_quantity_reports_data_required(
            self, app, db, working_version, activity_factory, today):
        activity = activity_factory(working_version, "1.9", "No quantity", today, today,
                                    progress_method="QUANTITY")
        result = forecasting.forecast_for_activity(activity, today)
        assert C.DATA_REQUIRED in result["message"]

    def test_forecast_table_only_covers_quantity_activities(
            self, app, db, working_version, activity_factory, piling, today):
        activity_factory(working_version, "1.1", "Manual activity", today, today)
        rows = forecasting.forecast_table(today)
        assert [r["activity"].wbs_code for r in rows] == ["1.3.2.2"]

    def test_window_length_is_configurable(self, app, db, piling, today):
        for offset in range(0, 12):
            self._record(db, "1.3.2.2", today - timedelta(days=offset), 10)
        seven = forecasting.forecast_for_activity(piling, today, window_days=7)
        fourteen = forecasting.forecast_for_activity(piling, today, window_days=14)
        assert seven["active_days"] == 7
        assert fourteen["active_days"] == 12
