"""Daily site report and weekly project-control report."""
from __future__ import annotations

from datetime import date, timedelta

from flask import Blueprint, render_template

from app.routes._helpers import arg_date, request_date
from app.services import reports as report_service

bp = Blueprint("reports", __name__, url_prefix="/reports")


@bp.route("/")
def index():
    today = date.today()
    week_start, week_end = report_service.week_bounds(today)
    from app.models import DailySiteReport
    recent = (DailySiteReport.query
              .order_by(DailySiteReport.report_date.desc()).limit(20).all())
    weeks = []
    cursor = week_start
    for _ in range(8):
        weeks.append((cursor, cursor + timedelta(days=6)))
        cursor -= timedelta(days=7)
    return render_template("reports/index.html", today=today, recent=recent,
                           week_start=week_start, week_end=week_end, weeks=weeks)


@bp.route("/daily")
def daily():
    report_date = request_date("date")
    context = report_service.daily_report(report_date)
    return render_template("reports/daily.html", **context)


@bp.route("/weekly")
def weekly():
    week_start = arg_date("week")
    context = report_service.weekly_report(week_start)
    return render_template("reports/weekly.html", **context)
