"""Permits and readiness register.

This is a status register only. The application records what has been issued
and what is outstanding; it offers no legal interpretation of any permit.
"""
from __future__ import annotations

from datetime import date

from flask import Blueprint, flash, redirect, render_template, request, url_for

from app import constants as C
from app.extensions import db
from app.i18n import translate as t
from app.models import PermitItem, SourceDocument
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
from app.services.status_rules import permit_status

bp = Blueprint("permits", __name__, url_prefix="/permits")

DISCLAIMER = (
    "This register records permit status only. It is not legal advice and does not "
    "confirm regulatory compliance. Verify every entry against the issuing authority."
)


@bp.route("/")
def index():
    as_of = request_date("as_of")
    summary = registers.permit_summary(as_of)
    status = arg_str("status")
    rows = summary["rows"]
    if status:
        rows = [pair for pair in rows if pair[1] == status]
    return render_template(
        "permits/index.html",
        as_of=as_of,
        rows=rows,
        summary=summary,
        status=status,
        disclaimer=DISCLAIMER,
        documents=SourceDocument.query.order_by(SourceDocument.title).all(),
    )


@bp.route("/new", methods=["POST"])
def create():
    name = form_str("item_name", max_length=300)
    if not name:
        flash(t("A permit / readiness item name is required."), "danger")
        return redirect(url_for("permits.index"))
    db.session.add(PermitItem(
        item_name=name,
        authority=form_str("authority", max_length=200),
        responsibility=form_str("responsibility", max_length=160),
        required_for=form_str("required_for", max_length=300),
        required_by_date=form_date("required_by_date"),
        issued_date=form_date("issued_date"),
        expiry_date=form_date("expiry_date"),
        status=form_str("status", "NOT STARTED"),
        document_reference=form_str("document_reference", max_length=300),
        blocker_impact=form_str("blocker_impact"),
        source_document_id=form_int("source_document_id"),
        verified=form_bool("verified"),
        comments=form_str("comments"),
    ))
    db.session.commit()
    flash(t("Permit / readiness item '{name}' registered.", name=name), "success")
    return redirect(url_for("permits.index"))


@bp.route("/<int:item_id>", methods=["GET", "POST"])
def detail(item_id):
    row = PermitItem.query.get_or_404(item_id)
    if request.method == "POST":
        if form_str("action") == "delete":
            name = row.item_name
            db.session.delete(row)
            db.session.commit()
            flash(t("'{name}' removed from the permit register.", name=name), "warning")
            return redirect(url_for("permits.index"))
        row.item_name = form_str("item_name", row.item_name, 300)
        row.authority = form_str("authority", row.authority, 200)
        row.responsibility = form_str("responsibility", row.responsibility, 160)
        row.required_for = form_str("required_for", row.required_for, 300)
        row.required_by_date = form_date("required_by_date", row.required_by_date)
        row.issued_date = form_date("issued_date", row.issued_date)
        row.expiry_date = form_date("expiry_date", row.expiry_date)
        row.status = form_str("status", row.status)
        row.document_reference = form_str("document_reference", row.document_reference, 300)
        row.blocker_impact = form_str("blocker_impact", row.blocker_impact)
        row.source_document_id = form_int("source_document_id", row.source_document_id)
        row.verified = form_bool("verified")
        row.comments = form_str("comments", row.comments)
        db.session.commit()
        flash(t("Permit register entry updated."), "success")
        return redirect(url_for("permits.detail", item_id=item_id))

    as_of = request_date("as_of")
    return render_template(
        "permits/detail.html",
        row=row,
        derived=permit_status(row, as_of),
        disclaimer=DISCLAIMER,
        documents=SourceDocument.query.order_by(SourceDocument.title).all(),
    )


@bp.route("/export.csv")
def export():
    filename, text = exporters.export_permits()
    return csv_response(filename, text)
