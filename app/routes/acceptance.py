"""Testing and contractual acceptance: Gates A-D and the document register.

Readiness is calculated. Acceptance is never calculated -- a gate only becomes
ACCEPTED when a user records that the Client accepted it.
"""
from __future__ import annotations

from datetime import date

from flask import Blueprint, flash, redirect, render_template, request, url_for

from app import constants as C
from app.extensions import db
from app.i18n import translate as t
from app.models import (
    AcceptanceGate,
    AcceptanceGateItem,
    DocumentRegisterItem,
    QualityRecord,
    SourceDocument,
)
from app.routes._helpers import (
    arg_str,
    csv_response,
    form_bool,
    form_date,
    form_int,
    form_str,
    request_date,
)
from app.services import exporters, registers
from app.services.status_rules import document_status

bp = Blueprint("acceptance", __name__, url_prefix="/acceptance")

HUMAN_DECISION_NOTE = (
    "Formal acceptance is a Client decision. The application reports readiness only and "
    "will never mark a gate accepted by itself."
)


@bp.route("/")
def index():
    as_of = request_date("as_of")
    overall = registers.overall_acceptance_readiness(as_of)
    return render_template(
        "acceptance/index.html",
        as_of=as_of,
        overall=overall,
        note=HUMAN_DECISION_NOTE,
        punch=registers.quality_query(record_type="PUNCH LIST"),
        tests=QualityRecord.query.filter_by(record_type="TEST RECORD")
              .order_by(QualityRecord.record_date.desc()).all(),
    )


@bp.route("/gate/<gate_code>", methods=["GET", "POST"])
def gate(gate_code):
    row = AcceptanceGate.query.filter_by(gate_code=gate_code.upper()).first_or_404()
    if request.method == "POST":
        row.target_date = form_date("target_date", row.target_date)
        row.notes = form_str("notes", row.notes)
        new_status = form_str("status", row.status)
        if new_status != row.status:
            if new_status == "ACCEPTED":
                row.actual_date = form_date("actual_date", date.today())
                row.accepted_by = form_str("accepted_by", max_length=160)
                if not row.accepted_by:
                    flash(t("Record who accepted the gate before marking it ACCEPTED."), "danger")
                    return redirect(url_for("acceptance.gate", gate_code=gate_code))
            else:
                row.actual_date = form_date("actual_date", row.actual_date)
            row.status = new_status
        else:
            row.actual_date = form_date("actual_date", row.actual_date)
            row.accepted_by = form_str("accepted_by", row.accepted_by, 160)
        db.session.commit()
        flash(t("Gate {gate_code} updated.", gate_code=row.gate_code), "success")
        return redirect(url_for("acceptance.gate", gate_code=gate_code))

    as_of = request_date("as_of")
    view = next((v for v in registers.gate_views(as_of) if v["gate"].id == row.id), None)
    return render_template(
        "acceptance/gate.html",
        view=view,
        as_of=as_of,
        note=HUMAN_DECISION_NOTE,
        documents=registers.document_summary(row.gate_code, as_of),
        punch=[r for r in registers.quality_query(record_type="PUNCH LIST")
               if r.gate_code == row.gate_code or not r.gate_code],
        sources=SourceDocument.query.order_by(SourceDocument.title).all(),
    )


@bp.route("/gate/<gate_code>/items", methods=["POST"])
def add_item(gate_code):
    row = AcceptanceGate.query.filter_by(gate_code=gate_code.upper()).first_or_404()
    name = form_str("item_name", max_length=400)
    if not name:
        flash(t("An item name is required."), "danger")
        return redirect(url_for("acceptance.gate", gate_code=gate_code))
    db.session.add(AcceptanceGateItem(
        gate_id=row.id,
        item_code=form_str("item_code", max_length=40),
        item_name=name,
        description=form_str("description"),
        category=form_str("category", max_length=80),
        responsible_party=form_str("responsible_party", max_length=160),
        target_date=form_date("target_date"),
        status=form_str("status", "NOT STARTED"),
        contract_reference=form_str("contract_reference", max_length=200),
        sequence=AcceptanceGateItem.query.filter_by(gate_id=row.id).count() + 1,
        source_document_id=form_int("source_document_id"),
        comments=form_str("comments"),
    ))
    db.session.commit()
    flash(t("Gate item added."), "success")
    return redirect(url_for("acceptance.gate", gate_code=gate_code))


@bp.route("/items/<int:item_id>", methods=["POST"])
def update_item(item_id):
    row = AcceptanceGateItem.query.get_or_404(item_id)
    gate_code = row.gate.gate_code
    if form_str("action") == "delete":
        db.session.delete(row)
        db.session.commit()
        flash(t("Gate item removed."), "warning")
        return redirect(url_for("acceptance.gate", gate_code=gate_code))

    row.item_code = form_str("item_code", row.item_code, 40)
    row.item_name = form_str("item_name", row.item_name, 400)
    row.description = form_str("description", row.description)
    row.category = form_str("category", row.category, 80)
    row.responsible_party = form_str("responsible_party", row.responsible_party, 160)
    row.target_date = form_date("target_date", row.target_date)
    row.evidence_reference = form_str("evidence_reference", row.evidence_reference, 400)
    row.contract_reference = form_str("contract_reference", row.contract_reference, 200)
    row.comments = form_str("comments", row.comments)
    new_status = form_str("status", row.status)
    if new_status != row.status:
        row.status = new_status
        if new_status in {"ACCEPTED", "SUBMITTED"}:
            row.actual_date = form_date("actual_date", date.today())
        elif new_status in {"NOT STARTED", "IN PROGRESS"}:
            row.actual_date = None
    else:
        row.actual_date = form_date("actual_date", row.actual_date)
    db.session.commit()
    flash(t("Gate item updated."), "success")
    return redirect(url_for("acceptance.gate", gate_code=gate_code))


# --------------------------------------------------------------------------
# Document register
# --------------------------------------------------------------------------
@bp.route("/documents", methods=["GET", "POST"])
def documents():
    if request.method == "POST":
        title = form_str("title", max_length=400)
        if not title:
            flash(t("A document title is required."), "danger")
            return redirect(url_for("acceptance.documents"))
        db.session.add(DocumentRegisterItem(
            document_number=form_str("document_number", max_length=120),
            title=title,
            category=form_str("category", max_length=60),
            discipline=form_str("discipline", max_length=60),
            wbs_code=form_str("wbs_code", max_length=60),
            revision=form_str("revision", max_length=60),
            status=form_str("status", "NOT STARTED"),
            issue_date=form_date("issue_date"),
            required_date=form_date("required_date"),
            submitted_date=form_date("submitted_date"),
            accepted_date=form_date("accepted_date"),
            source_path=form_str("source_path", max_length=500),
            gate_code=form_str("gate_code", max_length=4),
            mandatory=form_bool("mandatory"),
            folder_path=form_str("folder_path", max_length=400),
            source_document_id=form_int("source_document_id"),
            remarks=form_str("remarks"),
        ))
        db.session.commit()
        flash(t("Document '{title}' registered.", title=title), "success")
        return redirect(url_for("acceptance.documents"))

    as_of = request_date("as_of")
    gate_code = arg_str("gate")
    category = arg_str("category")
    summary = registers.document_summary(gate_code, as_of)
    rows = summary["rows"]
    if category:
        rows = [pair for pair in rows if pair[0].category == category]
    if arg_str("view") == "missing":
        rows = [pair for pair in rows
                if pair[0].mandatory and pair[0] in summary["missing_mandatory"]]
    return render_template(
        "acceptance/documents.html",
        rows=rows,
        summary=summary,
        gate_code=gate_code,
        category=category,
        view=arg_str("view"),
        as_of=as_of,
        gates=AcceptanceGate.query.order_by(AcceptanceGate.sequence).all(),
        sources=SourceDocument.query.order_by(SourceDocument.title).all(),
    )


@bp.route("/documents/<int:doc_id>", methods=["POST"])
def update_document(doc_id):
    row = DocumentRegisterItem.query.get_or_404(doc_id)
    if form_str("action") == "delete":
        db.session.delete(row)
        db.session.commit()
        flash(t("Document register entry removed."), "warning")
        return redirect(url_for("acceptance.documents"))
    row.document_number = form_str("document_number", row.document_number, 120)
    row.title = form_str("title", row.title, 400)
    row.category = form_str("category", row.category, 60)
    row.discipline = form_str("discipline", row.discipline, 60)
    row.wbs_code = form_str("wbs_code", row.wbs_code, 60)
    row.revision = form_str("revision", row.revision, 60)
    row.status = form_str("status", row.status)
    row.issue_date = form_date("issue_date", row.issue_date)
    row.required_date = form_date("required_date", row.required_date)
    row.submitted_date = form_date("submitted_date", row.submitted_date)
    row.accepted_date = form_date("accepted_date", row.accepted_date)
    row.source_path = form_str("source_path", row.source_path, 500)
    row.gate_code = form_str("gate_code", row.gate_code, 4)
    row.mandatory = form_bool("mandatory")
    row.folder_path = form_str("folder_path", row.folder_path, 400)
    row.remarks = form_str("remarks", row.remarks)
    if row.status == "ACCEPTED" and not row.accepted_date:
        row.accepted_date = date.today()
    db.session.commit()
    flash(t("Document register entry updated."), "success")
    return redirect(request.referrer or url_for("acceptance.documents"))


@bp.route("/export.csv")
def export():
    filename, text = exporters.export_acceptance()
    return csv_response(filename, text)


@bp.route("/documents/export.csv")
def export_documents():
    filename, text = exporters.export_documents()
    return csv_response(filename, text)
