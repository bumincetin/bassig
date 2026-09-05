"""Entering a day that is not today.

Site work is not always written up the same evening. A day recorded late must
land on its own date and must leave the running totals of every later day
correct, otherwise the cumulative column silently lies from that point on.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.models import DailyProgress, DailySiteReport
from app.services import progress as progress_service


def record(client, report_id, wbs, actual, planned=60, comments=""):
    return client.post(f"/daily/{report_id}/progress", data={
        "wbs_code": wbs, "planned_quantity": str(planned),
        "actual_quantity": str(actual), "workers": "9", "hours": "10",
        "comments": comments}, follow_redirects=True)


def open_day(client, day):
    client.get(f"/daily/today?date={day.isoformat()}", follow_redirects=True)
    return DailySiteReport.query.filter_by(report_date=day).one()


class TestOpeningAPastDay:
    def test_a_past_date_opens_a_diary_on_that_date(self, app, client):
        past = date.today() - timedelta(days=6)
        report = open_day(client, past)
        assert report.report_date == past

    def test_reopening_a_past_date_returns_the_same_diary(self, app, client):
        past = date.today() - timedelta(days=3)
        first = open_day(client, past)
        second = open_day(client, past)
        assert first.id == second.id
        assert DailySiteReport.query.count() == 1

    def test_a_future_date_is_refused(self, app, client):
        ahead = date.today() + timedelta(days=2)
        client.get(f"/daily/today?date={ahead.isoformat()}", follow_redirects=True)
        assert DailySiteReport.query.filter_by(report_date=ahead).count() == 0

    def test_the_date_picker_cannot_be_set_past_today(self, app, client):
        register = client.get("/daily/").get_data(as_text=True)
        assert f'max="{date.today().isoformat()}"' in register
        form = client.get("/daily/new").get_data(as_text=True)
        assert f'max="{date.today().isoformat()}"' in form

    def test_the_create_form_refuses_a_future_date(self, app, client):
        ahead = date.today() + timedelta(days=5)
        client.post("/daily/new", data={"report_date": ahead.isoformat(),
                                        "shift": "DAY"}, follow_redirects=True)
        assert DailySiteReport.query.count() == 0

    def test_a_day_that_is_not_today_says_so(self, app, client):
        past = date.today() - timedelta(days=4)
        report = open_day(client, past)
        page = client.get(f"/daily/{report.id}").get_data(as_text=True)
        assert "today" in page.lower()

    def test_report_numbers_stay_in_issue_order_not_date_order(self, app, client):
        """The number records when the diary was written up, so a back-dated
        day keeps the next number rather than renumbering the register."""
        later = open_day(client, date.today() - timedelta(days=2))
        earlier = open_day(client, date.today() - timedelta(days=9))
        assert later.report_number == "BAS-DSR-0001"
        assert earlier.report_number == "BAS-DSR-0002"
        assert earlier.report_date < later.report_date


class TestBackDatedQuantitiesRebase:
    def test_inserting_an_earlier_day_rebases_the_later_totals(self, app, client, db):
        day_2 = open_day(client, date(2026, 9, 2))
        day_4 = open_day(client, date(2026, 9, 4))
        record(client, day_2.id, "1.3.2.2", 40)
        record(client, day_4.id, "1.3.2.2", 30)

        # The 3rd is written up late, between two days that already carry totals.
        day_3 = open_day(client, date(2026, 9, 3))
        record(client, day_3.id, "1.3.2.2", 25)

        rows = (DailyProgress.query.filter_by(wbs_code="1.3.2.2")
                .order_by(DailyProgress.entry_date).all())
        assert [r.entry_date for r in rows] == [
            date(2026, 9, 2), date(2026, 9, 3), date(2026, 9, 4)]
        assert [r.cumulative_before for r in rows] == pytest.approx([0.0, 40.0, 65.0])
        assert [r.cumulative_after for r in rows] == pytest.approx([40.0, 65.0, 95.0])

    def test_the_user_is_told_that_later_totals_moved(self, app, client, db):
        day_2 = open_day(client, date(2026, 9, 2))
        day_4 = open_day(client, date(2026, 9, 4))
        record(client, day_2.id, "1.3.2.2", 40)
        record(client, day_4.id, "1.3.2.2", 30)
        day_3 = open_day(client, date(2026, 9, 3))
        page = record(client, day_3.id, "1.3.2.2", 25).get_data(as_text=True)
        assert "rebased" in page

    def test_deleting_a_middle_day_rebases_the_rest(self, app, client, db):
        days = [open_day(client, date(2026, 9, d)) for d in (2, 3, 4)]
        for report, quantity in zip(days, (40, 25, 30)):
            record(client, report.id, "1.3.2.2", quantity)

        middle = DailyProgress.query.filter_by(entry_date=date(2026, 9, 3)).one()
        client.post(f"/daily/progress/{middle.id}/delete", follow_redirects=True)

        rows = (DailyProgress.query.filter_by(wbs_code="1.3.2.2")
                .order_by(DailyProgress.entry_date).all())
        assert [r.cumulative_before for r in rows] == pytest.approx([0.0, 40.0])
        assert [r.cumulative_after for r in rows] == pytest.approx([40.0, 70.0])

    def test_two_activities_rebase_independently(self, app, client, db):
        day_2 = open_day(client, date(2026, 9, 2))
        day_4 = open_day(client, date(2026, 9, 4))
        record(client, day_2.id, "1.3.2.2", 40)
        record(client, day_4.id, "1.3.2.2", 30)
        record(client, day_4.id, "1.4.1.1", 12)

        day_3 = open_day(client, date(2026, 9, 3))
        record(client, day_3.id, "1.3.2.2", 25)

        other = DailyProgress.query.filter_by(wbs_code="1.4.1.1").one()
        assert other.cumulative_before == pytest.approx(0.0)
        assert other.cumulative_after == pytest.approx(12.0)


class TestRebaseService:
    def test_rebase_is_a_no_op_when_the_order_is_already_right(self, app, client, db):
        day_2 = open_day(client, date(2026, 9, 2))
        day_3 = open_day(client, date(2026, 9, 3))
        record(client, day_2.id, "1.3.2.2", 40)
        record(client, day_3.id, "1.3.2.2", 25)
        assert progress_service.rebase_cumulatives("1.3.2.2") == 0

    def test_rebase_repairs_a_directly_corrupted_running_total(self, app, client, db):
        day_2 = open_day(client, date(2026, 9, 2))
        day_3 = open_day(client, date(2026, 9, 3))
        record(client, day_2.id, "1.3.2.2", 40)
        record(client, day_3.id, "1.3.2.2", 25)

        broken = DailyProgress.query.filter_by(entry_date=date(2026, 9, 3)).one()
        broken.cumulative_before = 999.0
        db.session.commit()

        assert progress_service.rebase_cumulatives("1.3.2.2") == 1
        db.session.commit()
        assert broken.cumulative_before == pytest.approx(40.0)

    def test_rebase_without_a_wbs_code_does_nothing(self, app, db):
        assert progress_service.rebase_cumulatives(None) == 0
        assert progress_service.rebase_cumulatives("") == 0

    def test_rebase_all_covers_every_activity(self, app, client, db):
        day_2 = open_day(client, date(2026, 9, 2))
        day_3 = open_day(client, date(2026, 9, 3))
        for wbs in ("1.3.2.2", "1.4.1.1"):
            record(client, day_2.id, wbs, 10)
            record(client, day_3.id, wbs, 10)
        for row in DailyProgress.query.filter_by(entry_date=date(2026, 9, 3)):
            row.cumulative_before = 0.0
        db.session.commit()
        assert progress_service.rebase_all_cumulatives() == 2
