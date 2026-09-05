"""Deterministic arithmetic: achievement, productivity, weighted progress, forecast."""
from __future__ import annotations

from datetime import date

import pytest

from app.services import calculations as calc


class TestAchievement:
    def test_achievement_is_actual_over_planned(self):
        assert calc.achievement_pct(80, 100) == pytest.approx(80.0)

    def test_achievement_can_exceed_one_hundred(self):
        assert calc.achievement_pct(120, 100) == pytest.approx(120.0)

    def test_zero_planned_returns_none_not_zero(self):
        # A zero planned quantity makes achievement undefined. Reporting 0%
        # would misrepresent a day where work was done against no plan.
        assert calc.achievement_pct(50, 0) is None

    def test_missing_planned_returns_none(self):
        assert calc.achievement_pct(50, None) is None

    def test_zero_actual_against_a_plan_is_zero(self):
        assert calc.achievement_pct(0, 100) == pytest.approx(0.0)


class TestProductivity:
    def test_quantity_per_worker_day(self):
        assert calc.quantity_per_worker_day(120, 8) == pytest.approx(15.0)

    def test_quantity_per_worker_day_with_no_workers(self):
        assert calc.quantity_per_worker_day(120, 0) is None

    def test_quantity_per_worker_hour(self):
        assert calc.quantity_per_worker_hour(120, 8, 10) == pytest.approx(1.5)

    def test_quantity_per_worker_hour_with_zero_hours(self):
        assert calc.quantity_per_worker_hour(120, 8, 0) is None

    def test_quantity_per_worker_hour_with_zero_workers(self):
        assert calc.quantity_per_worker_hour(120, 0, 10) is None

    def test_man_hours_includes_overtime(self):
        assert calc.man_hours(10, 8, 12) == pytest.approx(92.0)


class TestQuantityProgress:
    def test_quantity_progress(self):
        assert calc.quantity_progress_pct(5000, 13965) == pytest.approx(35.8038, abs=1e-3)

    def test_progress_is_capped_at_one_hundred(self):
        assert calc.quantity_progress_pct(14000, 13965) == pytest.approx(100.0)

    def test_zero_total_required_is_undefined(self):
        assert calc.quantity_progress_pct(100, 0) is None


class TestWeightedProgress:
    def test_weighted_progress_is_not_a_mean(self):
        # A 90-day activity at 10% and a 10-day activity at 100% must not
        # average to 55%.
        items = [(90, 10.0), (10, 100.0)]
        assert calc.weighted_progress(items) == pytest.approx(19.0)

    def test_simple_mean_would_differ(self):
        items = [(90, 10.0), (10, 100.0)]
        weighted = calc.weighted_progress(items)
        mean = sum(p for _, p in items) / len(items)
        assert weighted != pytest.approx(mean)

    def test_zero_weight_items_are_ignored(self):
        assert calc.weighted_progress([(0, 100.0), (10, 50.0)]) == pytest.approx(50.0)

    def test_no_weighted_item_returns_none(self):
        assert calc.weighted_progress([(0, 100.0)]) is None

    def test_progress_cannot_exceed_one_hundred(self):
        assert calc.weighted_progress([(10, 250.0)]) == pytest.approx(100.0)

    def test_progress_cannot_go_below_zero(self):
        assert calc.weighted_progress([(10, -50.0)]) == pytest.approx(0.0)

    def test_non_numeric_entries_are_skipped(self):
        assert calc.weighted_progress([("x", "y"), (10, 40.0)]) == pytest.approx(40.0)


class TestElapsedPlanned:
    def test_before_start_is_zero(self):
        assert calc.elapsed_planned_pct(date(2026, 5, 1), date(2026, 5, 31),
                                        date(2026, 4, 1)) == 0.0

    def test_after_finish_is_one_hundred(self):
        assert calc.elapsed_planned_pct(date(2026, 5, 1), date(2026, 5, 31),
                                        date(2026, 7, 1)) == 100.0

    def test_midpoint(self):
        value = calc.elapsed_planned_pct(date(2026, 5, 1), date(2026, 5, 31),
                                         date(2026, 5, 16))
        assert value == pytest.approx(50.0)

    def test_missing_dates_return_none(self):
        assert calc.elapsed_planned_pct(None, date(2026, 5, 31), date(2026, 5, 16)) is None

    def test_zero_length_activity_is_complete_on_its_date(self):
        milestone = date(2026, 5, 11)
        assert calc.elapsed_planned_pct(milestone, milestone, milestone) == 100.0


class TestVarianceAndDelay:
    def test_variance_is_actual_minus_planned(self):
        assert calc.variance_pp(6.1, 44.4) == pytest.approx(-38.3)

    def test_variance_with_missing_value(self):
        assert calc.variance_pp(None, 44.4) is None

    def test_delay_days_positive_when_later(self):
        assert calc.delay_days(date(2027, 1, 27), date(2027, 3, 6)) == 38

    def test_delay_days_negative_when_earlier(self):
        assert calc.delay_days(date(2027, 3, 6), date(2027, 1, 27)) == -38

    def test_delay_days_with_missing_date(self):
        assert calc.delay_days(None, date(2027, 3, 6)) is None


class TestProductionRateAndForecast:
    def test_rate_ignores_idle_days(self):
        rate, active = calc.production_rate([100, 0, 0, 200, 150])
        assert active == 3
        assert rate == pytest.approx(150.0)

    def test_rate_with_no_production(self):
        rate, active = calc.production_rate([0, 0, 0])
        assert rate is None and active == 0

    def test_forecast_remaining_quantity_and_days(self):
        remaining, days = calc.forecast_remaining(13965, 5000, 150.0)
        assert remaining == pytest.approx(8965.0)
        assert days == pytest.approx(59.7666, abs=1e-3)

    def test_forecast_remaining_never_negative(self):
        remaining, _ = calc.forecast_remaining(100, 250, 10)
        assert remaining == 0.0

    def test_forecast_without_a_rate_gives_no_days(self):
        remaining, days = calc.forecast_remaining(100, 10, 0)
        assert remaining == pytest.approx(90.0)
        assert days is None

    def test_forecast_finish_date_spreads_over_working_week(self):
        finish = calc.forecast_finish_date(date(2026, 9, 4), 12, working_days_per_week=6)
        assert finish == date(2026, 9, 18)

    def test_forecast_finish_with_no_days_is_none(self):
        assert calc.forecast_finish_date(date(2026, 9, 4), None) is None


class TestStockAndUtilisation:
    def test_available_stock_formula(self):
        assert calc.available_stock(1000, 50, 400) == pytest.approx(650.0)

    def test_available_stock_can_be_negative_when_over_issued(self):
        assert calc.available_stock(100, 0, 250) == pytest.approx(-150.0)

    def test_utilisation(self):
        assert calc.utilisation_pct(6, 2, 0) == pytest.approx(75.0)

    def test_utilisation_with_no_hours(self):
        assert calc.utilisation_pct(0, 0, 0) is None


class TestSafeDivision:
    @pytest.mark.parametrize("numerator,denominator", [(1, 0), (None, 5), (5, None), ("a", 2)])
    def test_undefined_results_return_none(self, numerator, denominator):
        assert calc.safe_div(numerator, denominator) is None

    def test_pct_cap(self):
        assert calc.pct(3, 2, cap=100.0) == pytest.approx(100.0)
