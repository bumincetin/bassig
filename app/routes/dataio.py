"""Data Import / Export.

Import is always a two-step operation: upload and validate, then confirm.
Nothing is written to the database until the user confirms a validated preview.
"""
from __future__ import annotations

from pathlib import Path

from flask import (
    Blueprint,
    Response,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from app import constants as C
from app.extensions import db
from app.i18n import translate as t
from app.models import ImportBatch, ScheduleVersion, SourceDocument
from app.routes._helpers import arg_date, arg_str, csv_response, form_int, form_str
from app.services import exporters, importers
from app.services.status_rules import document_blocks_import

bp = Blueprint("dataio", __name__, url_prefix="/data")


@bp.route("/")
def index():
    return render_template(
        "dataio/index.html",
        specs=importers.SPECS,
        exports=exporters.EXPORTS,
        batches=ImportBatch.query.order_by(ImportBatch.created_at.desc()).limit(50).all(),
        versions=ScheduleVersion.query.order_by(ScheduleVersion.schedule_type,
                                                ScheduleVersion.effective_date).all(),
        documents=SourceDocument.query.order_by(SourceDocument.title).all(),
        prepared=importers.available_prepared_files(),
    )


@bp.route("/template/<key>.csv")
def template(key):
    spec = importers.SPECS.get(key)
    if spec is None:
        flash(t("Unknown import template."), "danger")
        return redirect(url_for("dataio.index"))
    return csv_response(f"bassignana_template_{key}.csv", spec.template_csv())


@bp.route("/import/<key>", methods=["POST"])
def start_import(key):
    spec = importers.SPECS.get(key)
    if spec is None:
        flash(t("Unknown import type."), "danger")
        return redirect(url_for("dataio.index"))

    prepared = form_str("prepared_file")
    upload = request.files.get("file")

    try:
        if prepared:
            path = Path(current_app.config["IMPORT_READY_DIR"]) / Path(prepared).name
            if not path.exists():
                flash(t("Prepared file '{prepared}' was not found.", prepared=prepared), "danger")
                return redirect(url_for("dataio.index"))
            token, name = importers.register_prepared_file(path)
        elif upload and upload.filename:
            token, name = importers.save_upload(upload)
        else:
            flash(t("Choose a file to import."), "danger")
            return redirect(url_for("dataio.index"))
    except ValueError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("dataio.index"))

    session[f"import_{key}"] = {
        "token": token,
        "filename": name,
        "version_id": form_int("version_id"),
        "document_id": form_int("source_document_id"),
    }
    return redirect(url_for("dataio.preview", key=key))


def _resolve_options(key):
    state = session.get(f"import_{key}")
    if not state:
        return None, None, None, None
    version = (db.session.get(ScheduleVersion, state["version_id"])
               if state.get("version_id") else None)
    document = (db.session.get(SourceDocument, state["document_id"])
                if state.get("document_id") else None)
    return state, version, document, state["token"]


@bp.route("/import/<key>/preview")
def preview(key):
    spec = importers.SPECS.get(key)
    state, version, document, token = _resolve_options(key)
    if spec is None or state is None:
        flash(t("No pending import for that template. Upload a file first."), "warning")
        return redirect(url_for("dataio.index"))

    blocking = []
    if key == "schedule" and version is None:
        blocking.append("Select the schedule version this programme belongs to. "
                        "Create it first in Schedule & WBS if it does not exist.")
    if version is not None and version.locked:
        blocking.append(f"Schedule version '{version.label}' is locked. Unlock it before "
                        f"importing, or import into a new version. The contractual baseline "
                        f"stays locked by design.")
    if document is not None and document_blocks_import(document):
        blocking.append(f"'{document.title}' is registered as {document.status}. A "
                        f"{document.status} document must not govern execution data. "
                        f"Register an approved revision, or reconcile it first.")

    try:
        path = importers.resolve_upload(token)
        headers, rows = importers.read_rows(path)
    except (FileNotFoundError, RuntimeError) as exc:
        flash(str(exc), "danger")
        session.pop(f"import_{key}", None)
        return redirect(url_for("dataio.index"))

    missing_columns = [c for c in spec.required if c not in headers]
    unknown_columns = [h for h in headers if h and h not in spec.columns]

    validation = importers.validate(key, rows, {"version": version, "source_document": document})

    return render_template(
        "dataio/preview.html",
        key=key, spec=spec, state=state, version=version, document=document,
        headers=headers, validation=validation,
        missing_columns=missing_columns, unknown_columns=unknown_columns,
        blocking=blocking,
        can_commit=not blocking and not missing_columns
                   and validation["summary"]["create"] + validation["summary"]["update"] > 0,
    )


@bp.route("/import/<key>/commit", methods=["POST"])
def commit(key):
    spec = importers.SPECS.get(key)
    state, version, document, token = _resolve_options(key)
    if spec is None or state is None:
        flash(t("No pending import to confirm."), "warning")
        return redirect(url_for("dataio.index"))
    if key == "schedule" and version is None:
        flash(t("Select a schedule version before committing a programme import."), "danger")
        return redirect(url_for("dataio.preview", key=key))
    if version is not None and version.locked:
        flash(t("That schedule version is locked and cannot be imported into."), "danger")
        return redirect(url_for("dataio.preview", key=key))
    if document is not None and document_blocks_import(document):
        flash(t("'{title}' is {status} and cannot be used as an import source.", title=document.title, status=document.status), "danger")
        return redirect(url_for("dataio.preview", key=key))

    try:
        path = importers.resolve_upload(token)
        _, rows = importers.read_rows(path)
    except (FileNotFoundError, RuntimeError) as exc:
        flash(str(exc), "danger")
        return redirect(url_for("dataio.index"))

    options = {"version": version, "source_document": document}
    validation = importers.validate(key, rows, options)
    batch = importers.commit(key, validation, options, filename=state["filename"])

    locked_now = False
    if version is not None:
        if document is not None and version.source_document_id is None:
            version.source_document_id = document.id
        # A contractual baseline locks itself as soon as it holds activities, so
        # a later working-programme import can never write over it.
        if version.is_contractual_baseline and not version.locked and batch.created_count:
            version.locked = True
            locked_now = True
        db.session.commit()

    session.pop(f"import_{key}", None)
    importers.purge_stale_uploads()
    message = t("{label} import committed: {created} created, {updated} updated, "
                "{skipped} skipped, {rejected} rejected.",
                label=spec.label, created=batch.created_count,
                updated=batch.updated_count, skipped=batch.skipped_count,
                rejected=batch.error_count)
    if locked_now:
        message += " " + t("'{label}' is now locked as the contractual baseline and "
                           "cannot be overwritten by a later programme.",
                           label=version.label)
    flash(message, "success")
    return redirect(url_for("dataio.index"))


@bp.route("/import/<key>/cancel", methods=["POST"])
def cancel(key):
    session.pop(f"import_{key}", None)
    importers.purge_stale_uploads(max_age_hours=0)
    flash(t("Import cancelled. Nothing was written to the database."), "warning")
    return redirect(url_for("dataio.index"))


@bp.route("/export/<key>.csv")
def export(key):
    entry = exporters.EXPORTS.get(key)
    if entry is None:
        flash(t("Unknown export."), "danger")
        return redirect(url_for("dataio.index"))
    _, function = entry
    filename, text = function(
        date_from=arg_date("from"),
        date_to=arg_date("to"),
        as_of=arg_date("as_of"),
        record_type=arg_str("type"),
    )
    return csv_response(filename, text)


@bp.route("/templates/write", methods=["POST"])
def write_templates():
    paths = importers.write_templates()
    flash(t("{paths} blank import templates written to project_data/import_templates/.", paths=len(paths)),
          "success")
    return redirect(url_for("dataio.index"))
