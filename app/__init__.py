"""BASSIGNANA EPC CONTROL -- application factory.

Bassignana Solar 2 -- Project & Site Control System.
Runs entirely locally: Flask + SQLAlchemy + SQLite, no external service of any
kind is contacted at runtime.
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from pathlib import Path

from flask import Flask, jsonify, request

from app import constants as C
from app.config import Config
from app.extensions import db

__version__ = "1.2.0"

BASE_DIR = Path(__file__).resolve().parent.parent
logger = logging.getLogger(__name__)


def create_app(config_object=Config):
    app = Flask(
        __name__,
        static_folder=str(BASE_DIR / "static"),
        template_folder=str(BASE_DIR / "templates"),
    )
    app.config.from_object(config_object)

    if app.config.get("BEHIND_PROXY"):
        # A hosting platform terminates HTTPS and forwards to us over plain
        # HTTP; trust its headers so URLs and cookies see the real scheme.
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)

    from app import auth, content_i18n, i18n, logging_setup, security
    logging_setup.init_app(app)

    if not app.config.get("TESTING"):
        app.config["SECRET_KEY"] = security.load_or_create_secret_key(app.config["DATA_DIR"])

    db.init_app(app)

    with app.app_context():
        # `from app import models` (not `import app.models`) so the local name
        # `app` keeps pointing at the Flask instance rather than the package.
        from app import models  # noqa: F401  (registers the mappers)
        from app.services import bootstrap, schema

        schema.apply_pragmas()
        db.create_all()
        report = schema.ensure_schema()
        if report["added_columns"] or report["created_tables"]:
            app.logger.info(
                "Schema reconciled to v%s: %s new table(s), %s new column(s)",
                report["version"], len(report["created_tables"]),
                len(report["added_columns"]))
        bootstrap.initialise()

    security.init_app(app)
    i18n.init_app(app)
    content_i18n.init_app(app)
    auth.init_app(app)
    register_blueprints(app)
    register_uploads(app)
    register_template_helpers(app)
    register_error_handlers(app)
    register_health(app)
    return app


def register_blueprints(app):
    from app.routes import (
        acceptance,
        backup as backup_routes,
        blockers,
        commercial,
        dashboard,
        daily,
        dataio,
        issues,
        permits,
        procurement,
        progress as progress_routes,
        quality,
        reports,
        rfi,
        schedule,
        setup,
        workforce,
    )

    app.register_blueprint(dashboard.bp)
    app.register_blueprint(schedule.bp)
    app.register_blueprint(daily.bp)
    app.register_blueprint(progress_routes.bp)
    app.register_blueprint(workforce.bp)
    app.register_blueprint(procurement.bp)
    app.register_blueprint(quality.bp)
    app.register_blueprint(issues.bp)
    app.register_blueprint(blockers.bp)
    app.register_blueprint(rfi.bp)
    app.register_blueprint(permits.bp)
    app.register_blueprint(acceptance.bp)
    app.register_blueprint(commercial.bp)
    app.register_blueprint(reports.bp)
    app.register_blueprint(dataio.bp)
    app.register_blueprint(setup.bp)
    app.register_blueprint(backup_routes.bp)


NAV = [
    ("dashboard.index", "Dashboard", "grid"),
    ("schedule.index", "Schedule & WBS", "calendar"),
    ("daily.index", "Daily Site", "clipboard"),
    ("progress.index", "Progress", "trend"),
    ("workforce.index", "Workforce & Plant", "people"),
    ("procurement.index", "Procurement & Materials", "box"),
    ("quality.index", "Quality", "check"),
    ("issues.index", "Issues / Punch / NCR", "flag"),
    ("blockers.index", "Blockers", "stop"),
    ("rfi.index", "RFI", "question"),
    ("permits.index", "Permits & Readiness", "stamp"),
    ("acceptance.index", "Testing & Acceptance", "award"),
    ("commercial.index", "Payment Milestones", "coin"),
    ("reports.index", "Reports", "file"),
    ("dataio.index", "Data Import / Export", "swap"),
    ("setup.index", "Project Setup", "gear"),
    ("backup.index", "Backup", "save"),
]


def register_template_helpers(app):
    from app.models import Project
    from app.services import data_health, progress as progress_service

    @app.template_filter("d")
    def _date(value, fmt=None):
        from app import i18n
        if fmt is None:
            return i18n.format_date(value)
        if value is None:
            return "-"
        if isinstance(value, datetime):
            return value.strftime(fmt + " %H:%M")
        if isinstance(value, date):
            return value.strftime(fmt)
        return str(value)

    @app.template_filter("iso")
    def _iso(value):
        if value is None:
            return ""
        if isinstance(value, (date, datetime)):
            return value.strftime("%Y-%m-%d")
        return str(value)

    @app.template_filter("num")
    def _num(value, digits=1):
        if value is None:
            return "-"
        try:
            return f"{float(value):,.{digits}f}"
        except (TypeError, ValueError):
            return str(value)

    @app.template_filter("money")
    def _money(value, currency="EUR", digits=0):
        if value is None:
            return "-"
        try:
            return f"{currency} {float(value):,.{digits}f}"
        except (TypeError, ValueError):
            return str(value)

    @app.template_filter("pc")
    def _percent(value, digits=1):
        if value is None:
            return "-"
        try:
            return f"{float(value):.{digits}f}%"
        except (TypeError, ValueError):
            return str(value)

    @app.template_filter("signed")
    def _signed(value, digits=1):
        if value is None:
            return "-"
        try:
            number = float(value)
        except (TypeError, ValueError):
            return str(value)
        return f"{number:+.{digits}f}"

    @app.template_filter("qty")
    def _qty(value, unit=None):
        if value is None:
            return "-"
        try:
            text = f"{float(value):,.2f}".rstrip("0").rstrip(".")
        except (TypeError, ValueError):
            return str(value)
        return f"{text} {unit}" if unit else text

    @app.template_filter("yn")
    def _yes_no(value):
        from app.i18n import translate
        return translate("Yes") if value else translate("No")

    @app.template_global("setting_label")
    def _setting_label(key):
        from app.services import settings as settings_service
        return settings_service.label_for(key)

    @app.template_global("badge")
    def _badge(value):
        return C.badge(value)

    @app.template_global("variance_class")
    def _variance_class(value):
        if value is None:
            return "text-muted"
        return "text-success" if value >= 0 else "text-danger"

    @app.context_processor
    def inject_globals():
        project = Project.query.first()
        health = data_health.report()
        return {
            "PROJECT": project,
            "NAV": NAV,
            "TODAY": date.today(),
            "C": C,
            "APP_VERSION": __version__,
            "HEALTH": health,
            "SETUP_INCOMPLETE": bool(health["missing_mandatory"]),
            "BASELINE_VERSION": progress_service.baseline_version(),
            "CURRENT_VERSION": progress_service.current_version(),
            "CURRENT_ENDPOINT": request.endpoint or "",
        }


def register_uploads(app):
    """Serve photographs and evidence from UPLOAD_DIR, wherever that is.

    Templates address them as /static/uploads/<path>. This route is more
    specific than the generic static route and therefore wins, so the folder
    can live on a persistent volume outside static/, and the access password
    (when one is set) applies to photographs as it does to every other
    project record.
    """
    from flask import send_from_directory

    @app.route("/static/uploads/<path:filename>", endpoint="uploads")
    def _uploads(filename):
        return send_from_directory(app.config["UPLOAD_DIR"], filename)


def register_health(app):
    """A machine-readable check, so the site team can confirm the server is up."""

    @app.route("/healthz")
    def healthz():
        from app.models import DailySiteReport, Project, WbsActivity
        from app.services import schema
        try:
            counts = {
                "activities": WbsActivity.query.count(),
                "daily_reports": DailySiteReport.query.count(),
            }
            project = Project.query.first()
            return jsonify({
                "status": "ok",
                "version": __version__,
                "schema_version": schema.current_version(),
                "project": project.name if project else None,
                "setup_complete": bool(project and project.setup_complete),
                "counts": counts,
                "server_time": datetime.now().isoformat(timespec="seconds"),
            })
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Health check failed")
            return jsonify({"status": "error", "detail": str(exc)}), 500


def register_error_handlers(app):
    from flask import render_template

    @app.errorhandler(400)
    def _bad_request(error):
        return render_template(
            "error.html", code=400,
            message=getattr(error, "description",
                            "The request could not be processed.")), 400

    @app.errorhandler(404)
    def _not_found(error):
        return render_template("error.html", code=404,
                               message="That page does not exist."), 404

    @app.errorhandler(413)
    def _too_large(error):
        return render_template(
            "error.html", code=413,
            message="The uploaded file is larger than the 64 MB limit."), 413

    @app.errorhandler(500)
    def _server_error(error):  # pragma: no cover - defensive
        app.logger.exception("Unhandled error on %s", request.path)
        db.session.rollback()
        return render_template(
            "error.html", code=500,
            message="An unexpected error occurred and the database transaction was "
                    "rolled back. The details have been written to the log file in "
                    "data/logs/bassignana.log."), 500

    @app.teardown_request
    def _rollback_on_error(exception):
        if exception is not None:
            db.session.rollback()
