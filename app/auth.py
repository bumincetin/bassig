"""Optional shared-password access control for a hosted installation.

On a private site LAN the application deliberately has no login: everyone in
the site office has the same access, and a password would only get in the way
of a daily entry. When the same application is published on the internet so
that the whole company can use it, an open URL would let anyone who finds it
read and change the project record. Setting BASSIGNANA_ACCESS_PASSWORD turns
on a single shared password:

* every page except the static assets and the health check redirects to a
  login screen until the password has been entered once;
* the session then stays signed in for 30 days on that device;
* a wrong password is answered slowly and, after repeated failures from one
  address, refused for a while, so the password cannot be guessed quickly;
* the password itself is never written to the database or the log.

Leaving the variable empty keeps the open LAN behaviour exactly as before.
"""
from __future__ import annotations

import hmac
import logging
import threading
import time

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from app.i18n import translate as t

logger = logging.getLogger(__name__)

bp = Blueprint("auth", __name__)

SESSION_KEY = "_access_granted"

#: Endpoints reachable without signing in. Photographs and evidence files are
#: served by the `uploads` endpoint and are NOT listed here on purpose: they
#: are project records too.
OPEN_ENDPOINTS = {"static", "auth.login", "healthz"}

_failures: dict[str, list[float]] = {}
_failures_lock = threading.Lock()


def enabled():
    return bool(current_app.config.get("ACCESS_PASSWORD"))


def is_authenticated():
    return session.get(SESSION_KEY) is True


def _client_address():
    return request.remote_addr or "unknown"


def _lockout_remaining(address):
    """Seconds this address must still wait, or 0."""
    limit = current_app.config.get("LOGIN_MAX_FAILURES", 8)
    window = current_app.config.get("LOGIN_LOCKOUT_SECONDS", 300)
    now = time.monotonic()
    with _failures_lock:
        stamps = [s for s in _failures.get(address, []) if now - s < window]
        _failures[address] = stamps
        if len(stamps) >= limit:
            return window - (now - stamps[0])
    return 0


def _record_failure(address):
    with _failures_lock:
        _failures.setdefault(address, []).append(time.monotonic())


def _clear_failures(address):
    with _failures_lock:
        _failures.pop(address, None)


def reset_lockouts():
    """Forget every failed attempt. Used by the tests."""
    with _failures_lock:
        _failures.clear()


def _safe_next(target):
    """Only ever redirect within this application."""
    target = (target or "").strip()
    if target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return None


@bp.route("/login", methods=["GET", "POST"])
def login():
    if not enabled():
        return redirect(url_for("dashboard.index"))
    destination = _safe_next(request.args.get("next")) or url_for("dashboard.index")
    if is_authenticated():
        return redirect(destination)

    error = None
    if request.method == "POST":
        address = _client_address()
        remaining = _lockout_remaining(address)
        if remaining > 0:
            minutes = max(1, int(remaining // 60) + (1 if remaining % 60 else 0))
            error = t("Too many failed attempts. Try again in {minutes} minute(s).",
                      minutes=minutes)
            logger.warning("Login refused for %s: locked out", address)
        else:
            submitted = (request.form.get("password") or "").encode("utf-8")
            expected = current_app.config["ACCESS_PASSWORD"].encode("utf-8")
            if hmac.compare_digest(submitted, expected):
                _clear_failures(address)
                session[SESSION_KEY] = True
                session.permanent = True
                logger.info("Signed in from %s", address)
                return redirect(destination)
            _record_failure(address)
            logger.warning("Wrong password from %s", address)
            delay = current_app.config.get("LOGIN_FAILURE_DELAY") or 0
            if delay:
                time.sleep(delay)
            error = t("The password is not correct.")

    return render_template("auth/login.html", error=error, next=destination)


@bp.route("/logout", methods=["POST"])
def logout():
    session.pop(SESSION_KEY, None)
    flash(t("Signed out."), "info")
    return redirect(url_for("auth.login") if enabled() else url_for("dashboard.index"))


def require_login():
    """Send an unauthenticated request to the login screen."""
    if not enabled():
        return None
    endpoint = request.endpoint or ""
    if endpoint in OPEN_ENDPOINTS or is_authenticated():
        return None
    if request.method in {"GET", "HEAD"}:
        wanted = request.full_path.rstrip("?") if request.query_string else request.path
        return redirect(url_for("auth.login", next=wanted))
    return redirect(url_for("auth.login"))


def init_app(app):
    app.register_blueprint(bp)
    app.before_request(require_login)

    @app.context_processor
    def _inject():
        return {"AUTH_ENABLED": enabled(),
                "AUTHENTICATED": enabled() and is_authenticated()}
