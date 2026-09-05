"""Project Setup: identity, source-document register, areas, thresholds and the
first-run initialisation wizard.
"""
from __future__ import annotations

from pathlib import Path

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)

from app import constants as C
from app.extensions import db
from app.i18n import translate as t
from app.models import Area, ImportBatch, Project, ScheduleVersion, SourceDocument
from app.routes._helpers import (
    arg_int,
    arg_str,
    csv_response,
    form_bool,
    form_date,
    form_float,
    form_int,
    form_str,
    save_document,
)
from app.services import data_health, exporters, importers, progress, settings

bp = Blueprint("setup", __name__, url_prefix="/setup")

WIZARD_STEPS = [
    (1, "Project identity", "setup.project"),
    (2, "Register source documents", "setup.documents"),
    (3, "Import contractual baseline schedule", "dataio.index"),
    (4, "Import current working schedule", "dataio.index"),
    (5, "Import WBS quantities", "dataio.index"),
    (6, "Import areas / workfronts", "setup.areas"),
    (7, "Import procurement packages and payment milestones", "dataio.index"),
    (8, "Import quality / ITP requirements", "dataio.index"),
    (9, "Configure thresholds", "setup.thresholds"),
    (10, "Validation report", "setup.validation"),
]


@bp.route("/")
def index():
    health = data_health.report()
    return render_template(
        "setup/index.html",
        health=health,
        steps=WIZARD_STEPS,
        project=Project.query.first(),
        documents=SourceDocument.query.order_by(SourceDocument.document_type,
                                                SourceDocument.title).all(),
        versions=ScheduleVersion.query.all(),
        areas=Area.query.count(),
        batches=ImportBatch.query.order_by(ImportBatch.created_at.desc()).limit(10).all(),
        reconciliation=data_health.reconciliation_flags(),
        schedule_warnings=data_health.schedule_health(),
    )


# --------------------------------------------------------------------------
# Step 1 - project identity
# --------------------------------------------------------------------------
@bp.route("/project", methods=["GET", "POST"])
def project():
    row = Project.query.first()
    if request.method == "POST":
        row.name = form_str("name", row.name, 200)
        row.subtitle = form_str("subtitle", row.subtitle, 250)
        row.plant_name = form_str("plant_name", row.plant_name, 200)
        row.client = form_str("client", row.client, 200)
        row.epc_contractor = form_str("epc_contractor", row.epc_contractor, 200)
        row.contract_reference = form_str("contract_reference", row.contract_reference, 200)
        row.ntp_date = form_date("ntp_date", row.ntp_date)
        row.contract_completion_date = form_date("contract_completion_date",
                                                 row.contract_completion_date)
        row.comune = form_str("comune", row.comune, 120)
        row.provincia = form_str("provincia", row.provincia, 120)
        row.regione = form_str("regione", row.regione, 120)
        row.country = form_str("country", row.country, 80)
        row.nominal_dc_kwp = form_float("nominal_dc_kwp", row.nominal_dc_kwp)
        row.nominal_ac_kw = form_float("nominal_ac_kw", row.nominal_ac_kw)
        row.grid_voltage_kv = form_float("grid_voltage_kv", row.grid_voltage_kv)
        row.dso = form_str("dso", row.dso, 120)
        row.pod_code = form_str("pod_code", row.pod_code, 60)
        row.authorisation_reference = form_str("authorisation_reference",
                                               row.authorisation_reference, 200)
        row.cadastral_reference = form_str("cadastral_reference", row.cadastral_reference, 400)
        row.contract_price = form_float("contract_price", row.contract_price)
        row.currency = form_str("currency", row.currency, 10)
        row.delay_lds_pct_per_day = form_float("delay_lds_pct_per_day",
                                               row.delay_lds_pct_per_day)
        row.delay_lds_cap_pct = form_float("delay_lds_cap_pct", row.delay_lds_cap_pct)
        row.delay_termination_days = form_int("delay_termination_days",
                                              row.delay_termination_days)
        row.performance_bond_pct = form_float("performance_bond_pct", row.performance_bond_pct)
        row.advance_payment_pct = form_float("advance_payment_pct", row.advance_payment_pct)
        row.dnp_months = form_int("dnp_months", row.dnp_months)
        row.guaranteed_pr_note = form_str("guaranteed_pr_note", row.guaranteed_pr_note, 300)
        row.min_availability_pct = form_float("min_availability_pct", row.min_availability_pct)
        row.adverse_wind_ms = form_float("adverse_wind_ms", row.adverse_wind_ms)
        row.adverse_rain_mm_h = form_float("adverse_rain_mm_h", row.adverse_rain_mm_h)
        row.notes = form_str("notes", row.notes)
        db.session.commit()
        flash(t("Project identity saved."), "success")
        return redirect(url_for("setup.project"))
    return render_template("setup/project.html", row=row)


# --------------------------------------------------------------------------
# Step 2 - source document register
# --------------------------------------------------------------------------
@bp.route("/documents", methods=["GET", "POST"])
def documents():
    if request.method == "POST":
        title = form_str("title", max_length=300)
        if not title:
            flash(t("A document title is required."), "danger")
            return redirect(url_for("setup.documents"))

        source_filename = form_str("source_filename", max_length=300)
        stored_path = None
        upload = request.files.get("file")
        if upload and upload.filename:
            try:
                original, stored = save_document(upload, current_app.config["SOURCE_DOC_DIR"])
                source_filename = source_filename or original
                stored_path = stored
            except ValueError as exc:
                flash(str(exc), "danger")
                return redirect(url_for("setup.documents"))

        status = form_str("status", "DRAFT")
        doc = SourceDocument(
            document_type=form_str("document_type", "OTHER", 60),
            title=title,
            source_filename=source_filename,
            stored_path=stored_path,
            revision=form_str("revision", max_length=60),
            document_date=form_date("document_date"),
            effective_date=form_date("effective_date"),
            status=status,
            contractual=form_bool("contractual") or status == "CONTRACTUAL BASELINE",
            supersedes_document_id=form_int("supersedes_document_id"),
            source_reference=form_str("source_reference", max_length=300),
            notes=form_str("notes"),
        )
        db.session.add(doc)
        db.session.flush()
        # Superseding never deletes: the prior revision is retained and marked.
        if doc.supersedes_document_id:
            prior = db.session.get(SourceDocument, doc.supersedes_document_id)
            if prior is not None and prior.status not in {"SUPERSEDED"}:
                prior.status = "SUPERSEDED"
                prior.notes = ((prior.notes or "") +
                               f"\nSuperseded by '{doc.title}'"
                               f"{f' rev. {doc.revision}' if doc.revision else ''}.").strip()
        db.session.commit()
        flash(t("Source document '{title}' registered as {status}.", title=title, status=status), "success")
        return redirect(url_for("setup.documents"))

    document_type = arg_str("type")
    status = arg_str("status")
    query = SourceDocument.query
    if document_type:
        query = query.filter(SourceDocument.document_type == document_type)
    if status:
        query = query.filter(SourceDocument.status == status)
    return render_template(
        "setup/documents.html",
        rows=query.order_by(SourceDocument.document_type, SourceDocument.title).all(),
        all_documents=SourceDocument.query.order_by(SourceDocument.title).all(),
        filters={"type": document_type, "status": status},
        reconciliation=data_health.reconciliation_flags(),
    )


@bp.route("/documents/<int:doc_id>", methods=["POST"])
def update_document(doc_id):
    row = SourceDocument.query.get_or_404(doc_id)
    action = form_str("action")
    if action == "delete":
        title = row.title
        db.session.delete(row)
        db.session.commit()
        flash(t("'{title}' removed from the source document register. Any records that referenced it now show no source.", title=title), "warning")
        return redirect(url_for("setup.documents"))

    row.document_type = form_str("document_type", row.document_type, 60)
    row.title = form_str("title", row.title, 300)
    row.revision = form_str("revision", row.revision, 60)
    row.document_date = form_date("document_date", row.document_date)
    row.effective_date = form_date("effective_date", row.effective_date)
    row.status = form_str("status", row.status)
    row.contractual = form_bool("contractual") or row.status == "CONTRACTUAL BASELINE"
    row.source_reference = form_str("source_reference", row.source_reference, 300)
    row.notes = form_str("notes", row.notes)
    db.session.commit()
    flash(t("'{title}' updated.", title=row.title), "success")
    return redirect(url_for("setup.documents"))


@bp.route("/documents/<int:doc_id>/file")
def document_file(doc_id):
    row = SourceDocument.query.get_or_404(doc_id)
    if not row.stored_path:
        flash(t("No file was uploaded for that register entry."), "warning")
        return redirect(url_for("setup.documents"))
    return send_from_directory(current_app.config["SOURCE_DOC_DIR"], row.stored_path,
                               as_attachment=True, download_name=row.source_filename)


@bp.route("/documents/export.csv")
def export_documents():
    filename, text = exporters.export_source_documents()
    return csv_response(filename, text)


# --------------------------------------------------------------------------
# Step 6 - areas / workfronts
# --------------------------------------------------------------------------
@bp.route("/areas", methods=["GET", "POST"])
def areas():
    if request.method == "POST":
        code = form_str("area_code", max_length=60)
        name = form_str("area_name", max_length=200)
        if not code or not name:
            flash(t("An area code and name are both required."), "danger")
            return redirect(url_for("setup.areas"))
        if Area.query.filter_by(area_code=code).first():
            flash(t("Area '{code}' already exists.", code=code), "warning")
            return redirect(url_for("setup.areas"))
        db.session.add(Area(
            area_code=code,
            area_name=name,
            description=form_str("description"),
            parent_area_id=form_int("parent_area_id"),
            drawing_reference=form_str("drawing_reference", max_length=200),
            ifc_revision=form_str("ifc_revision", max_length=60),
            active=True,
            source_document_id=form_int("source_document_id"),
            notes=form_str("notes"),
        ))
        db.session.commit()
        flash(t("Workfront '{code}' created.", code=code), "success")
        return redirect(url_for("setup.areas"))

    rows = Area.query.order_by(Area.area_code).all()
    return render_template(
        "setup/areas.html",
        rows=rows,
        documents=SourceDocument.query.order_by(SourceDocument.title).all(),
        needs_area_data=not rows,
    )


@bp.route("/areas/<int:area_id>", methods=["POST"])
def update_area(area_id):
    row = Area.query.get_or_404(area_id)
    action = form_str("action")
    if action == "delete":
        code = row.area_code
        db.session.delete(row)
        db.session.commit()
        flash(t("Workfront '{code}' deleted.", code=code), "warning")
        return redirect(url_for("setup.areas"))
    if action == "toggle":
        row.active = not row.active
        db.session.commit()
        flash(t("Workfront '{area_code}' marked {inactive}.", area_code=row.area_code, inactive='active' if row.active else 'inactive'), "success")
        return redirect(url_for("setup.areas"))

    row.area_name = form_str("area_name", row.area_name, 200)
    row.description = form_str("description", row.description)
    row.parent_area_id = form_int("parent_area_id", row.parent_area_id)
    row.drawing_reference = form_str("drawing_reference", row.drawing_reference, 200)
    row.ifc_revision = form_str("ifc_revision", row.ifc_revision, 60)
    row.source_document_id = form_int("source_document_id", row.source_document_id)
    row.notes = form_str("notes", row.notes)
    db.session.commit()
    flash(t("Workfront '{area_code}' updated.", area_code=row.area_code), "success")
    return redirect(url_for("setup.areas"))


@bp.route("/areas/export.csv")
def export_areas():
    filename, text = exporters.export_areas()
    return csv_response(filename, text)


# --------------------------------------------------------------------------
# Step 9 - thresholds
# --------------------------------------------------------------------------
@bp.route("/thresholds", methods=["GET", "POST"])
def thresholds():
    if request.method == "POST":
        changed = 0
        for key in settings.DEFAULT_SETTINGS:
            if key in request.form:
                settings.set_value(key, request.form.get(key))
                changed += 1
        db.session.commit()
        flash(t("{changed} setting(s) saved. Classifications recalculate immediately.", changed=changed),
              "success")
        return redirect(url_for("setup.thresholds"))
    return render_template("setup/thresholds.html", grouped=settings.all_grouped(),
                           defaults=settings.DEFAULT_SETTINGS)


@bp.route("/thresholds/reset", methods=["POST"])
def reset_thresholds():
    for key, spec in settings.DEFAULT_SETTINGS.items():
        settings.set_value(key, spec[0])
    db.session.commit()
    flash(t("All thresholds reset to their defaults."), "warning")
    return redirect(url_for("setup.thresholds"))


# --------------------------------------------------------------------------
# Step 10 - validation
# --------------------------------------------------------------------------
@bp.route("/validation")
def validation():
    health = data_health.report()
    return render_template(
        "setup/validation.html",
        health=health,
        steps=WIZARD_STEPS,
        reconciliation=data_health.reconciliation_flags(),
        schedule_warnings=data_health.schedule_health(),
        basis=progress.weighting_basis_report(),
        prepared=importers.available_prepared_files(),
    )


@bp.route("/complete", methods=["POST"])
def complete():
    row = Project.query.first()
    health = data_health.report()
    if health["missing_mandatory"]:
        flash(t("Setup cannot be marked complete while mandatory master data is missing. Resolve every DATA REQUIRED item first."), "danger")
        return redirect(url_for("setup.validation"))
    row.setup_complete = True
    row.setup_step = 10
    db.session.commit()
    flash(t("Project setup marked complete. All mandatory master data is registered."),
          "success")
    return redirect(url_for("dashboard.index"))


@bp.route("/reopen", methods=["POST"])
def reopen():
    row = Project.query.first()
    row.setup_complete = False
    db.session.commit()
    flash(t("Project setup reopened."), "warning")
    return redirect(url_for("setup.index"))
