"""Dashboard: where Bassignana is, what is late, why, and what is next."""
from __future__ import annotations

from flask import Blueprint, jsonify, render_template

from app.routes._helpers import request_date
from app.services import dashboard as dashboard_service

bp = Blueprint("dashboard", __name__)


@bp.route("/")
def index():
    as_of = request_date("as_of")
    context = dashboard_service.build(as_of)
    return render_template("dashboard/index.html", **context)


@bp.route("/dashboard/charts.json")
def charts():
    as_of = request_date("as_of")
    context = dashboard_service.build(as_of)
    return jsonify(dashboard_service.charts(context))
