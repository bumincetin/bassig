"""Schedule variance, classification, baseline separation and lookaheads."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from app import constants as C
from app.models import ScheduleVersion, WbsActivity
from app.services import progress, schedule_service, settings
from app.services.status_rules import (
    classify_schedule_variance,
    is_overdue_incomplete_milestone,
)


class TestClassification:
    def test_on_track_at_threshold(self, app):
        assert classify_schedule_variance(-5.0) == C.SCHEDULE_CLASS_ON_TRACK

    def test_on_track_above_threshold(self, app):
        assert classify_schedule_variance(0.0) == C.SCHEDULE_CLASS_ON_TRACK

    def test_at_risk_between_thresholds(self, app):
        assert classify_schedule_variance(-7.5) == C.SCHEDULE_CLASS_AT_RISK

    def test_at_risk_at_critical_boundary(self, app):
        assert classify_schedule_variance(-10.0) == C.SCHEDULE_CLASS_AT_RISK

    def test_critical_below_threshold(self, app):
        assert classify_schedule_variance(-10.1) == C.SCHEDULE_CLASS_CRITICAL

    def test_missing_variance_is_on_track(self, app):
        assert classify_schedule_variance(None) == C.SCHEDULE_CLASS_ON_TRACK

    def test_thresholds_are_configurable(self, app, db):
        settings.set_value("variance_critical_pp", -2.0)
        settings.set_value("variance_at_risk_pp", -1.0)
        db.session.commit()
        assert classify_schedule_variance(-3.0) == C.SCHEDULE_CLASS_CRITICAL

    def test_overdue_milestone_forces_critical(self, app):
        assert classify_schedule_variance(50.0, overdue_incomplete_milestone=True) \
            == C.SCHEDULE_CLASS_CRITICAL


class TestOverdueMilestone:
    def test_incomplete_milestone_past_its_date_is_overdue(
            self, app, db, working_version, activity_factory, today):
        activity = activity_factory(
            working_version, "1.4.3.5", "PV PLANT MECHANICAL COMPLETION",
            today - timedelta(days=10), today - timedelta(days=10),
            is_milestone=True, reported_completion_pct=0.0)
        assert is_overdue_incomplete_milestone(activity, today) is True

    def test_complete_milestone_is_not_overdue(
            self, app, db, working_version, activity_factory, today):
        activity = activity_factory(
            working_version, "1.4.3.5", "PV PLANT MECHANICAL COMPLETION",
            today - timedelta(days=10), today - timedelta(days=10),
            is_milestone=True, reported_completion_pct=100.0)
        assert is_overdue_incomplete_milestone(activity, today) is False

    def test_future_milestone_is_not_overdue(
            self, app, db, working_version, activity_factory, today):
        activity = activity_factory(
            working_version, "1.5.1.1", "PV PLANT ENERGIZATION",
            today + timedelta(days=30), today + timedelta(days=30),
            is_milestone=True)
        assert is_overdue_incomplete_milestone(activity, today) is False

    def test_non_milestone_is_never_flagged(
            self, app, db, working_version, activity_factory, today):
        activity = activity_factory(
            working_version, "1.3.2.2", "Foundation Piles Ramming",
            today - timedelta(days=30), today - timedelta(days=10))
        assert is_overdue_incomplete_milestone(activity, today) is False

    def test_overdue_milestone_is_reported_critical_in_the_comparison(
            self, app, db, working_version, activity_factory, today):
        activity_factory(working_version, "1.4.3.5", "PV PLANT MECHANICAL COMPLETION",
                         today - timedelta(days=10), today - timedelta(days=10),
                         is_milestone=True, reported_completion_pct=0.0)
        rows = schedule_service.comparison_rows(today)
        assert rows[0]["classification"] == C.SCHEDULE_CLASS_CRITICAL
        assert rows[0]["overdue_milestone"] is True


class TestBaselineSeparation:
    def test_baseline_and_working_are_separate_versions(
            self, app, baseline_version, working_version):
        assert baseline_version.id != working_version.id
        assert baseline_version.is_contractual_baseline is True
        assert working_version.is_contractual_baseline is False

    def test_importing_a_working_programme_does_not_touch_baseline_dates(
            self, app, db, baseline_version, working_version):
        from app.services import importers
        rows_baseline = [{
            "wbs_code": "1.3.2.2", "activity_name": "Foundation Piles Ramming",
            "contractual_start": "2026-08-11", "contractual_finish": "2026-09-09",
            "current_planned_start": "2026-08-11", "current_planned_finish": "2026-09-09",
            "duration_days": "30",
        }]
        options = {"version": baseline_version}
        importers.commit("schedule", importers.validate("schedule", rows_baseline, options),
                         options)

        rows_working = [{
            "wbs_code": "1.3.2.2", "activity_name": "Foundation Piles Ramming",
            "current_planned_start": "2026-10-07", "current_planned_finish": "2026-11-05",
            "duration_days": "30",
        }]
        options = {"version": working_version}
        importers.commit("schedule", importers.validate("schedule", rows_working, options),
                         options)

        baseline_activity = WbsActivity.query.filter_by(
            schedule_version_id=baseline_version.id, wbs_code="1.3.2.2").one()
        working_activity = WbsActivity.query.filter_by(
            schedule_version_id=working_version.id, wbs_code="1.3.2.2").one()

        assert baseline_activity.baseline_start == date(2026, 8, 11)
        assert baseline_activity.baseline_finish == date(2026, 9, 9)
        # The working programme keeps its own dates and writes no contractual dates.
        assert working_activity.plan_start == date(2026, 10, 7)
        assert working_activity.baseline_start is None
        assert working_activity.baseline_finish is None

    def test_comparison_reports_the_slip_against_the_baseline(
            self, app, db, baseline_version, working_version, activity_factory, today):
        activity_factory(baseline_version, "1.3.2.2", "Foundation Piles Ramming",
                         date(2026, 8, 11), date(2026, 9, 9))
        activity_factory(working_version, "1.3.2.2", "Foundation Piles Ramming",
                         date(2026, 10, 7), date(2026, 11, 5))
        rows = schedule_service.comparison_rows(today)
        row = rows[0]
        assert row["baseline_start"] == date(2026, 8, 11)
        assert row["plan_start"] == date(2026, 10, 7)
        assert row["start_delay_days"] == 57
        assert row["finish_delay_days"] == 57


class TestBaselineMatching:
    def test_matched_by_name_when_the_wbs_code_was_renumbered(
            self, app, db, baseline_version, working_version, activity_factory, today):
        # Bassignana renumbered Topography Investigations from 1.1.1.7 to 1.1.1.2.
        activity_factory(baseline_version, "1.1.1.7", "Topography Investigations",
                         date(2026, 5, 11), date(2026, 5, 13))
        activity_factory(working_version, "1.1.1.2", "Topography Investigations",
                         date(2026, 6, 16), date(2026, 6, 16))
        row = schedule_service.comparison_rows(today)[0]
        assert row["match_kind"] == "NAME"
        assert row["baseline_start"] == date(2026, 5, 11)

    def test_new_scope_is_reported_unmatched(
            self, app, db, baseline_version, working_version, activity_factory, today):
        activity_factory(working_version, "1.1.1.3", "Topography Investigations - Final Report",
                         date(2026, 7, 8), date(2026, 7, 8))
        rows = schedule_service.comparison_rows(today)
        assert rows[0]["match_kind"] == "UNMATCHED"
        assert len(schedule_service.unmatched_to_baseline(rows)) == 1

    def test_manual_link_overrides_name_matching(
            self, app, db, baseline_version, working_version, activity_factory, today):
        activity_factory(baseline_version, "1.2.3.6", "TVCC System",
                         date(2026, 7, 5), date(2026, 7, 24))
        activity_factory(working_version, "1.2.2.6", "CCTV System & Lighting",
                         date(2026, 9, 2), date(2026, 9, 21),
                         baseline_link_wbs="1.2.3.6")
        row = schedule_service.comparison_rows(today)[0]
        assert row["match_kind"] == "MANUAL LINK"
        assert row["baseline_start"] == date(2026, 7, 5)


class TestFilteredViews:
    @pytest.fixture()
    def populated(self, db, working_version, activity_factory, today):
        activity_factory(working_version, "1.1", "Overdue activity",
                         today - timedelta(days=40), today - timedelta(days=5),
                         reported_completion_pct=20.0)
        activity_factory(working_version, "1.2", "Late start activity",
                         today - timedelta(days=3), today + timedelta(days=20),
                         reported_completion_pct=0.0)
        activity_factory(working_version, "1.3", "Starting soon",
                         today + timedelta(days=3), today + timedelta(days=30))
        activity_factory(working_version, "1.4", "Finishing soon",
                         today - timedelta(days=20), today + timedelta(days=4),
                         reported_completion_pct=80.0)
        activity_factory(working_version, "1.5", "Far future",
                         today + timedelta(days=200), today + timedelta(days=260))
        return schedule_service.comparison_rows(today)

    def test_overdue(self, app, populated, today):
        codes = {r["wbs_code"] for r in schedule_service.overdue_rows(populated, today)}
        assert codes == {"1.1"}

    def test_late_start(self, app, populated, today):
        codes = {r["wbs_code"] for r in schedule_service.late_start_rows(populated, today)}
        assert "1.2" in codes

    def test_starting_within_seven_days(self, app, populated, today):
        codes = {r["wbs_code"] for r in schedule_service.starting_within(populated, 7, today)}
        assert codes == {"1.3"}

    def test_finishing_within_seven_days(self, app, populated, today):
        codes = {r["wbs_code"] for r in schedule_service.finishing_within(populated, 7, today)}
        assert codes == {"1.4"}

    def test_two_week_lookahead_excludes_far_future(self, app, populated, today):
        codes = {r["wbs_code"] for r in schedule_service.lookahead(populated, 2, today)}
        assert "1.5" not in codes

    def test_four_week_lookahead_is_wider_than_two_week(self, app, populated, today):
        two = len(schedule_service.lookahead(populated, 2, today))
        four = len(schedule_service.lookahead(populated, 4, today))
        assert four >= two

    def test_critical_workfronts_are_ranked_worst_first(
            self, app, db, working_version, activity_factory, today):
        activity_factory(working_version, "2.1", "Bad", today - timedelta(days=50),
                         today + timedelta(days=10), work_package="Civil",
                         reported_completion_pct=0.0)
        activity_factory(working_version, "2.2", "Fine", today - timedelta(days=50),
                         today + timedelta(days=10), work_package="Electrical",
                         reported_completion_pct=95.0)
        rows = schedule_service.comparison_rows(today)
        ranked = schedule_service.critical_workfronts(rows)
        assert ranked[0]["work_package"] == "Civil"


class TestRecoveryComparison:
    def test_recovery_comparison_reports_slip(
            self, app, db, baseline_version, working_version, activity_factory, today):
        activity_factory(baseline_version, "1.6.3.2",
                         "PV PLANT PROVISIONAL ACCEPTANCE CERTIFICATE",
                         date(2027, 1, 22), date(2027, 1, 22), is_milestone=True)
        activity_factory(working_version, "1.6.4.2",
                         "PV PLANT PROVISIONAL ACCEPTANCE CERTIFICATE",
                         date(2027, 3, 1), date(2027, 3, 1), is_milestone=True)
        result = schedule_service.recovery_comparison(today)
        assert len(result) == 1
        assert result[0]["max_finish_slip"] == 38
        assert result[0]["project_finish"] == date(2027, 3, 1)

    def test_no_comparison_without_a_baseline(self, app, db, working_version):
        assert schedule_service.recovery_comparison() == []


class TestGoverningVersion:
    def test_working_version_governs_by_default(self, app, baseline_version, working_version):
        assert progress.governing_version().id == working_version.id

    def test_baseline_governs_when_configured(self, app, db, baseline_version, working_version):
        settings.set_value("governing_schedule", "CONTRACTUAL BASELINE")
        db.session.commit()
        assert progress.governing_version().id == baseline_version.id

    def test_baseline_is_used_when_no_working_programme_exists(self, app, baseline_version):
        assert progress.current_version().id == baseline_version.id
