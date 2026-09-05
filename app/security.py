"""Local-installation safety measures.

There is no authentication in this MVP by design: everyone on the site LAN has
the same access. That makes two things matter more, not less:

* a stable secret key, so sessions and the import preview survive a restart;
* CSRF protection, so a page opened on a site tablet cannot be used by another
  site to post into this application without the user noticing.

Both are implemented here without adding a dependency.
"""
from __future__ import annotations

import hmac
import logging
import os
import re
import secrets
from pathlib import Path

from flask import abort, current_app, request, session

logger = logging.getLogger(__name__)

#: Matches an opening <form ...> tag that posts. The token is injected into
#: every such tag on the way out, so a form can never be added to a template
#: and accidentally left unprotected.
_POST_FORM = re.compile(
    rb'<form\b(?![^>]*\bmethod\s*=\s*["\']?get)[^>]*\bmethod\s*=\s*["\']?post["\']?[^>]*>',
    re.IGNORECASE,
)

SECRET_FILENAME = "secret_key"
CSRF_SESSION_KEY = "_csrf_token"
CSRF_FORM_FIELD = "_csrf_token"
CSRF_HEADER = "X-CSRF-Token"

#: Endpoints that legitimately accept a POST without a browser session, if any
#: are ever added. Empty by design.
CSRF_EXEMPT = set()


def load_or_create_secret_key(data_dir):
    """Read the persisted secret key, creating it on first run.

    Keeping it on disk (rather than regenerating each start) means a site
    tablet does not lose its session, and a half-finished import preview is not
    thrown away, every time the server is restarted.
    """
    override = os.environ.get("BASSIGNANA_SECRET_KEY")
    if override:
        return override

    path = Path(data_dir) / SECRET_FILENAME
    if path.exists():
        value = path.read_text(encoding="utf-8").strip()
        if value:
            return value

    value = secrets.token_urlsafe(48)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:  # pragma: no cover - Windows may refuse
        pass
    logger.info("Generated a new secret key at %s", path)
    return value


def csrf_token():
    """The session's CSRF token, created on first use."""
    token = session.get(CSRF_SESSION_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        session[CSRF_SESSION_KEY] = token
    return token


def _submitted_token():
    return (request.form.get(CSRF_FORM_FIELD)
            or request.headers.get(CSRF_HEADER)
            or "")


def protect():
    """Reject an unsafe request that carries no valid CSRF token."""
    if request.method in {"GET", "HEAD", "OPTIONS", "TRACE"}:
        return
    if current_app.config.get("WTF_CSRF_ENABLED") is False:
        return
    if request.endpoint in CSRF_EXEMPT:
        return

    expected = session.get(CSRF_SESSION_KEY)
    submitted = _submitted_token()
    if not expected or not submitted or not hmac.compare_digest(expected, submitted):
        logger.warning("Rejected %s %s: CSRF token missing or invalid",
                       request.method, request.path)
        abort(400, description=(
            "This form could not be submitted because its security token was missing or "
            "out of date. This usually means the page had been left open for a long time. "
            "Reload the page and try again -- nothing was saved."
        ))


def inject_form_tokens(response):
    """Add the CSRF token to every posting form in an HTML response.

    Doing it here rather than in each template means a form added to a template
    later cannot be left unprotected by omission.
    """
    if current_app.config.get("WTF_CSRF_ENABLED") is False:
        return response
    if response.direct_passthrough or not response.mimetype == "text/html":
        return response
    body = response.get_data()
    if b"<form" not in body.lower():
        return response

    field = (f'<input type="hidden" name="{CSRF_FORM_FIELD}" '
             f'value="{csrf_token()}">').encode("utf-8")

    def _add(match):
        return match.group(0) + field

    new_body, count = _POST_FORM.subn(_add, body)
    if count:
        response.set_data(new_body)
    return response


def init_app(app):
    app.config.setdefault("SESSION_COOKIE_HTTPONLY", True)
    app.config.setdefault("SESSION_COOKIE_SAMESITE", "Lax")
    # No HTTPS on a site LAN, so the cookie must not be marked Secure.
    app.config.setdefault("SESSION_COOKIE_SECURE", False)
    app.config.setdefault("MAX_COOKIE_SIZE", 8192)
    app.config.setdefault("PERMANENT_SESSION_LIFETIME", 60 * 60 * 24 * 30)

    app.before_request(protect)

    @app.after_request
    def _finalise(response):
        response = inject_form_tokens(response)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        return response

    @app.context_processor
    def _inject_csrf():
        return {"csrf_token": csrf_token}
