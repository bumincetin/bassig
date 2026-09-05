"""Cross-cutting register queries: quality, RFI, issues, blockers, permits,
documents and acceptance gates.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import func

from app import constants as C
from app.extensions import db
from app.models import (
    AcceptanceGate,
    Blocker,
    DocumentRegisterItem,
    Issue,
    PermitItem,
    QualityRecord,
    Rfi,
    SiteObservation,
)
from app.services.calculations import pct, safe_div
from app.services.status_rules import (
    document_status,
    gate_derived_state,
    gate_readiness,
    is_overdue,
    permit_status,
    quality_status,
    rfi_status,
)


# --------------------------------------------------------------------------
# Quality
# --------------------------------------------------------------------------
def quality_query(record_type=None, status=None, area_id=None, wbs=None,
                  date_from=None, date_to=None, overdue_only=False):
    query = QualityRecord.query
    if record_type:
        query = query.filter(QualityRecord.record_type == record_type)
    if status:
        query = query.filter(QualityRecord.status == status)
    if area_id:
        query = query.filter(QualityRecord.area_id == area_id)
    if wbs:
        query = query.filter(QualityRecord.wbs_code.like(f"{wbs}%"))
    if date_from:
        query = query.filter(QualityRecord.record_date >= date_from)
    if date_to:
        query = query.filter(QualityRecord.record_date <= date_to)
    rows = query.order_by(QualityRecord.record_date.desc(), QualityRecord.id.desc()).all()
    if overdue_only:
        rows = [r for r in rows if quality_status(r) == "OVERDUE"]
    return rows


def open_quality(record_type=None, as_of=None):
    query = QualityRecord.query.filter(QualityRecord.status.in_(sorted(C.QUALITY_OPEN_STATES)))
    if record_type:
        query = query.filter(QualityRecord.record_type == record_type)
    return query.order_by(QualityRecord.target_closure_date.asc().nulls_last()
                          if hasattr(QualityRecord.target_closure_date.asc(), "nulls_last")
                          else QualityRecord.target_closure_date).all()


def overdue_quality(record_type=None, as_of=None):
    as_of = as_of or date.today()
    rows = open_quality(record_type)
    return [r for r in rows
            if is_overdue(r.target_closure_date, r.status, C.QUALITY_CLOSED_STATES, as_of)]


def quality_summary(as_of=None):
    as_of = as_of or date.today()
    counts = dict(db.session.query(QualityRecord.record_type, func.count(QualityRecord.id))
                  .group_by(QualityRecord.record_type).all())
    open_counts = dict(db.session.query(QualityRecord.record_type, func.count(QualityRecord.id))
                       .filter(QualityRecord.status.in_(sorted(C.QUALITY_OPEN_STATES)))
                       .group_by(QualityRecord.record_type).all())
    by_status = dict(db.session.query(QualityRecord.status, func.count(QualityRecord.id))
                     .group_by(QualityRecord.status).all())
    return {
        "total": counts,
        "open": open_counts,
        "by_status": by_status,
        "open_ncr": int(open_counts.get("NCR", 0)),
        "open_punch": int(open_counts.get("PUNCH LIST", 0)),
        "open_inspection": int(open_counts.get("INSPECTION", 0)),
        "overdue_ncr": len(overdue_quality("NCR", as_of)),
        "overdue_punch": len(overdue_quality("PUNCH LIST", as_of)),
        "hold_points": QualityRecord.query.filter(
            QualityRecord.record_type == "ITP POINT",
            QualityRecord.status.in_(sorted(C.QUALITY_OPEN_STATES)),
        ).count(),
    }


# --------------------------------------------------------------------------
# RFI
# --------------------------------------------------------------------------
def rfi_summary(as_of=None):
    as_of = as_of or date.today()
    rows = Rfi.query.all()
    statuses = [rfi_status(r, as_of) for r in rows]
    return {
        "total": len(rows),
        "open": sum(1 for s in statuses if s == "OPEN"),
        "overdue": sum(1 for s in statuses if s == "OVERDUE"),
        "answered": sum(1 for s in statuses if s == "ANSWERED"),
        "closed": sum(1 for s in statuses if s == "CLOSED"),
        "schedule_impact": sum(1 for r in rows if r.schedule_impact
                               and rfi_status(r, as_of) not in {"CLOSED"}),
    }


def overdue_rfis(as_of=None):
    as_of = as_of or date.today()
    return [r for r in Rfi.query.order_by(Rfi.required_response_date).all()
            if rfi_status(r, as_of) == "OVERDUE"]


# --------------------------------------------------------------------------
# Issues / actions
# --------------------------------------------------------------------------
def issue_summary(as_of=None):
    as_of = as_of or date.today()
    rows = Issue.query.all()
    open_rows = [r for r in rows if (r.status or "OPEN").upper() in C.ACTION_OPEN_STATES]
    overdue = [r for r in open_rows if r.target_date and r.target_date < as_of]
    by_category = defaultdict(int)
    for row in open_rows:
        by_category[row.category or "Other"] += 1
    return {
        "total": len(rows),
        "open": len(open_rows),
        "overdue": len(overdue),
        "by_category": dict(by_category),
        "overdue_rows": overdue,
    }


def overdue_observations(as_of=None):
    as_of = as_of or date.today()
    return (SiteObservation.query
            .filter(SiteObservation.status != "CLOSED")
            .filter(SiteObservation.target_date.isnot(None))
            .filter(SiteObservation.target_date < as_of)
            .order_by(SiteObservation.target_date).all())


# --------------------------------------------------------------------------
# Blockers
# --------------------------------------------------------------------------
def blocker_summary(date_from=None, date_to=None):
    query = Blocker.query
    if date_from:
        query = query.filter(Blocker.entry_date >= date_from)
    if date_to:
        query = query.filter(Blocker.entry_date <= date_to)
    rows = query.all()

    by_category = defaultdict(lambda: {"incidents": 0, "lost_hours": 0.0, "lost_man_hours": 0.0})
    by_area = defaultdict(lambda: {"incidents": 0, "lost_hours": 0.0})
    by_activity = defaultdict(lambda: {"incidents": 0, "lost_hours": 0.0})

    for row in rows:
        hours = row.effective_lost_hours
        cat = by_category[row.category or "Other"]
        cat["incidents"] += 1
        cat["lost_hours"] += hours
        cat["lost_man_hours"] += row.lost_man_hours
        area_key = row.area.label if row.area else "Not allocated"
        by_area[area_key]["incidents"] += 1
        by_area[area_key]["lost_hours"] += hours
        act_key = row.activity or row.wbs_code or "Unspecified"
        by_activity[act_key]["incidents"] += 1
        by_activity[act_key]["lost_hours"] += hours

    open_rows = [r for r in rows if (r.status or "OPEN").upper() in C.ACTION_OPEN_STATES]
    categories = sorted(
        ({"category": k, **v} for k, v in by_category.items()),
        key=lambda r: -r["lost_hours"],
    )
    return {
        "rows": rows,
        "total": len(rows),
        "open": len(open_rows),
        "open_rows": open_rows,
        "lost_hours": sum(r.effective_lost_hours for r in rows),
        "lost_man_hours": sum(r.lost_man_hours for r in rows),
        "by_category": categories,
        "by_area": sorted(({"area": k, **v} for k, v in by_area.items()),
                          key=lambda r: -r["lost_hours"]),
        "by_activity": sorted(({"activity": k, **v} for k, v in by_activity.items()),
                              key=lambda r: -r["lost_hours"]),
        "top_cause": categories[0] if categories else None,
        "recurring": [c for c in categories if c["incidents"] >= 3],
    }


# --------------------------------------------------------------------------
# Permits
# --------------------------------------------------------------------------
def permit_summary(as_of=None):
    as_of = as_of or date.today()
    rows = PermitItem.query.order_by(PermitItem.required_by_date).all()
    statuses = [(r, permit_status(r, as_of)) for r in rows]
    return {
        "rows": statuses,
        "total": len(rows),
        "issued": sum(1 for _, s in statuses if s == "ISSUED"),
        "open": sum(1 for _, s in statuses if s not in {"ISSUED", "NOT APPLICABLE"}),
        "overdue": sum(1 for _, s in statuses if s == "OVERDUE"),
        "expired": sum(1 for _, s in statuses if s == "EXPIRED"),
        "unverified": sum(1 for r in rows if not r.verified),
    }


# --------------------------------------------------------------------------
# Documents
# --------------------------------------------------------------------------
def document_summary(gate_code=None, as_of=None):
    as_of = as_of or date.today()
    query = DocumentRegisterItem.query
    if gate_code:
        query = query.filter(DocumentRegisterItem.gate_code == gate_code)
    rows = query.order_by(DocumentRegisterItem.category, DocumentRegisterItem.title).all()
    statuses = [(r, document_status(r, as_of)) for r in rows]
    mandatory = [r for r in rows if r.mandatory]
    missing = [r for r in mandatory
               if (r.status or "NOT STARTED").upper() not in C.DOCUMENT_CLOSED_STATES]
    return {
        "rows": statuses,
        "total": len(rows),
        "mandatory": len(mandatory),
        "missing_mandatory": missing,
        "missing_count": len(missing),
        "accepted": sum(1 for _, s in statuses if s == "ACCEPTED"),
        "overdue": sum(1 for _, s in statuses if s == "OVERDUE"),
        "completeness_pct": pct(len(mandatory) - len(missing), len(mandatory), cap=100.0),
    }


# --------------------------------------------------------------------------
# Acceptance gates
# --------------------------------------------------------------------------
def gate_views(as_of=None):
    as_of = as_of or date.today()
    views = []
    for gate in AcceptanceGate.query.order_by(AcceptanceGate.sequence, AcceptanceGate.gate_code).all():
        readiness, satisfied, considered = gate_readiness(gate.items)
        docs = document_summary(gate.gate_code, as_of)
        views.append({
            "gate": gate,
            "readiness_pct": readiness,
            "satisfied": satisfied,
            "considered": considered,
            "derived_state": gate_derived_state(gate, readiness),
            "recorded_status": gate.status,
            "documents": docs,
            "open_items": [i for i in gate.items
                           if (i.status or "").upper() not in
                           (C.GATE_ITEM_SATISFIED | C.GATE_ITEM_EXCLUDED)],
            "rejected_items": [i for i in gate.items if (i.status or "").upper() == "REJECTED"],
        })
    return views


def overall_acceptance_readiness(as_of=None):
    """Mean readiness of the four gates, weighted by item count."""
    views = gate_views(as_of)
    total_considered = sum(v["considered"] for v in views)
    total_satisfied = sum(v["satisfied"] for v in views)
    ratio = safe_div(total_satisfied, total_considered)
    return {
        "percent": None if ratio is None else ratio * 100.0,
        "satisfied": total_satisfied,
        "considered": total_considered,
        "gates": views,
    }
