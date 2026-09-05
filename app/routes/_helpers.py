"""Shared helpers for route handlers.

Route handlers stay thin: they parse the request, call a service and render.
"""
from __future__ import annotations

import re
import uuid
from datetime import date, datetime
from pathlib import Path

from flask import Response, current_app, request
from werkzeug.utils import secure_filename

from app.extensions import db
from app.i18n import translate as t
from app.models import Photo


# --------------------------------------------------------------------------
# Request parsing
# --------------------------------------------------------------------------
def form_str(name, default=None, max_length=None, source=None):
    source = source if source is not None else request.form
    value = (source.get(name) or "").strip()
    if not value:
        return default
    if max_length:
        value = value[:max_length]
    return value


def form_int(name, default=None, source=None):
    source = source if source is not None else request.form
    raw = (source.get(name) or "").strip()
    if raw == "":
        return default
    try:
        return int(float(raw.replace(",", ".")))
    except ValueError:
        return default


def form_float(name, default=None, source=None):
    source = source if source is not None else request.form
    raw = (source.get(name) or "").strip().replace("%", "")
    if raw == "":
        return default
    try:
        return float(raw.replace(",", "."))
    except ValueError:
        return default


def form_bool(name, source=None):
    source = source if source is not None else request.form
    return (source.get(name) or "").strip().lower() in {"1", "true", "on", "yes", "y"}


def form_date(name, default=None, source=None):
    source = source if source is not None else request.form
    raw = (source.get(name) or "").strip()
    if not raw:
        return default
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return default


def form_datetime(name, default=None, source=None):
    source = source if source is not None else request.form
    raw = (source.get(name) or "").strip()
    if not raw:
        return default
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return default


def arg_date(name, default=None):
    return form_date(name, default, source=request.args)


def arg_str(name, default=None):
    return form_str(name, default, source=request.args)


def arg_int(name, default=None):
    return form_int(name, default, source=request.args)


def request_date(name="date", default=None):
    """Date from the query string, falling back to today."""
    return arg_date(name, default if default is not None else date.today())


# --------------------------------------------------------------------------
# Photographs / evidence
# --------------------------------------------------------------------------
def save_photos(files, caption=None, taken_date=None, **links):
    """Store uploaded photographs and attach them to a record."""
    stored = []
    allowed = current_app.config["ALLOWED_PHOTO_EXT"]
    upload_dir = Path(current_app.config["UPLOAD_DIR"])
    for file_storage in files or []:
        if not file_storage or not file_storage.filename:
            continue
        suffix = Path(file_storage.filename).suffix.lower()
        if suffix not in allowed:
            continue
        subdir = (taken_date or date.today()).strftime("%Y-%m")
        target_dir = upload_dir / subdir
        target_dir.mkdir(parents=True, exist_ok=True)
        safe = secure_filename(Path(file_storage.filename).name) or "photo"
        name = f"{uuid.uuid4().hex[:12]}_{safe}"
        file_storage.save(target_dir / name)
        photo = Photo(
            filename=Path(file_storage.filename).name,
            stored_path=f"{subdir}/{name}",
            caption=caption,
            taken_date=taken_date or date.today(),
            **links,
        )
        db.session.add(photo)
        stored.append(photo)
    return stored


def save_document(file_storage, directory, prefix=""):
    """Store a registered source document / evidence file."""
    if not file_storage or not file_storage.filename:
        return None, None
    suffix = Path(file_storage.filename).suffix.lower()
    if suffix not in current_app.config["ALLOWED_DOC_EXT"]:
        raise ValueError(t("File type '{suffix}' is not accepted for document registration.",
                           suffix=suffix))
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    safe = secure_filename(Path(file_storage.filename).name) or "document"
    name = f"{prefix}{uuid.uuid4().hex[:8]}_{safe}" if prefix else f"{uuid.uuid4().hex[:8]}_{safe}"
    file_storage.save(directory / name)
    return Path(file_storage.filename).name, name


# --------------------------------------------------------------------------
# Responses
# --------------------------------------------------------------------------
def csv_response(filename, text):
    return Response(
        text,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def paginate(query, page=None, per_page=100):
    page = page or arg_int("page", 1) or 1
    total = query.count()
    rows = query.limit(per_page).offset((page - 1) * per_page).all()
    pages = max((total + per_page - 1) // per_page, 1)
    return {
        "rows": rows,
        "page": page,
        "pages": pages,
        "total": total,
        "per_page": per_page,
        "has_prev": page > 1,
        "has_next": page < pages,
    }


def slugify(value):
    return re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")
