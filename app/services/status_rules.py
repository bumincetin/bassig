"""Centralised project-status classification.

Every status decision in the application is made here. Templates receive an
already-classified value and never re-derive one.
"""
from __future__ import annotations

from datetime import date

from app import constants as C
from app.services import settings
from app.services.calculations import safe_div


# --------------------------------------------------------------------------
# Schedule classification
# --------------------------------------------------------------------------
def classify_schedule_variance(variance, overdue_incomplete_milestone=False):
    """ON TRACK / AT RISK / CRITICAL from a variance in percentage points.

    An overdue incomplete milestone is CRITICAL regardless of variance.
    """
    if overdue_incomplete_milestone:
        return C.SCHEDULE_CLASS_CRITICAL
    if variance is None:
        return C.SCHEDULE_CLASS_ON_TRACK
    at_risk = settings.get("variance_at_risk_pp", -5.0)
    critical = settings.get("variance_critical_pp", -10.0)
    if variance < critical:
        return C.SCHEDULE_CLASS_CRITICAL
    if variance < at_risk:
        return C.SCHEDULE_CLASS_AT_RISK
    return C.SCHEDULE_CLASS_ON_TRACK


def is_overdue_incomplete_milestone(activity, as_of=None):
    """True when a milestone's planned finish has passed and it is not complete."""
    if activity is None or not getattr(activity, "is_milestone", False):
        return False
    as_of = as_of or date.today()
    if (activity.reported_completion_pct or 0.0) >= 100.0:
        return False
    if activity.actual_finish:
        return False
    target = activity.plan_finish or activity.baseline_finish
    return bool(target and target < as_of)


def activity_status(activity, as_of=None):
    """Derived execution status of an activity."""
    as_of = as_of or date.today()
    if activity.status in {"ON HOLD", "CANCELLED"}:
        return activity.status
    completion = activity.reported_completion_pct or 0.0
    if activity.actual_finish or completion >= 100.0:
        return "COMPLETE"
    if activity.actual_start or completion > 0.0:
        return "IN PROGRESS"
    return "NOT STARTED"


# --------------------------------------------------------------------------
# Action-style records
# --------------------------------------------------------------------------
def action_status(current_status, target_date, closed_date=None, as_of=None):
    """OPEN / IN PROGRESS / OVERDUE / CLOSED for issues, observations, blockers."""
    as_of = as_of or date.today()
    normalized = (current_status or "OPEN").upper()
    if normalized == "CLOSED" or closed_date:
        return "CLOSED"
    if target_date and target_date < as_of:
        return "OVERDUE"
    if normalized in C.ACTION_OPEN_STATES:
        return normalized
    return "OPEN"


def is_overdue(target_date, status, closed_states, as_of=None):
    """Generic overdue test used by quality, RFI and document registers."""
    if not target_date:
        return False
    if (status or "").upper() in closed_states:
        return False
    return target_date < (as_of or date.today())


# --------------------------------------------------------------------------
# Quality
# --------------------------------------------------------------------------
def quality_status(record, as_of=None):
    """Reported status of a quality record, flagging overdue open items."""
    status = (record.status or "OPEN").upper()
    if status in C.QUALITY_CLOSED_STATES:
        return status
    if is_overdue(record.target_closure_date, status, C.QUALITY_CLOSED_STATES, as_of):
        return "OVERDUE"
    return status


def quality_is_open(record):
    return (record.status or "OPEN").upper() in C.QUALITY_OPEN_STATES


# --------------------------------------------------------------------------
# RFI
# --------------------------------------------------------------------------
def rfi_status(rfi, as_of=None):
    status = (rfi.status or "OPEN").upper()
    if status in {"CLOSED", "ANSWERED"}:
        return status
    if is_overdue(rfi.required_response_date, status, {"CLOSED", "ANSWERED"}, as_of):
        return "OVERDUE"
    return status


# --------------------------------------------------------------------------
# Procurement
# --------------------------------------------------------------------------
def procurement_status(package_or_material, as_of=None):
    """ON TIME / AT RISK / LATE / DELIVERED / ACCEPTED / INSTALLED.

    Delivered, accepted and installed are distinct states and are reported from
    the recorded quantities only -- never inferred from one another.
    """
    as_of = as_of or date.today()
    obj = package_or_material

    required = getattr(obj, "total_required", None)
    installed = getattr(obj, "installed", None)
    accepted = getattr(obj, "accepted", None)
    delivered = getattr(obj, "delivered", None)

    if required and installed is not None and installed >= required > 0:
        return "INSTALLED"
    if required and accepted is not None and accepted >= required > 0:
        return "ACCEPTED"
    if required and delivered is not None and delivered >= required > 0:
        return "DELIVERED"

    if getattr(obj, "actual_delivery", None):
        return "DELIVERED"

    target = getattr(obj, "forecast_delivery", None) or getattr(obj, "planned_delivery", None)
    if not target:
        return "ON TIME"
    if target < as_of:
        return "LATE"
    at_risk_days = settings.get("procurement_at_risk_days", 14)
    if (target - as_of).days <= at_risk_days:
        return "AT RISK"
    return "ON TIME"


def delivery_is_late(obj, as_of=None):
    return procurement_status(obj, as_of) == "LATE"


# --------------------------------------------------------------------------
# Stock
# --------------------------------------------------------------------------
def stock_status(available, remaining_requirement):
    """OK / LOW STOCK / SHORTAGE."""
    if remaining_requirement is None or remaining_requirement <= 0:
        return C.STOCK_OK
    if available is None:
        return C.STOCK_SHORTAGE
    if available <= 0:
        return C.STOCK_SHORTAGE
    low_pct = settings.get("stock_low_pct", 20.0)
    ratio = safe_div(available, remaining_requirement)
    if ratio is None:
        return C.STOCK_OK
    if ratio * 100.0 < low_pct:
        return C.STOCK_LOW
    return C.STOCK_OK


# --------------------------------------------------------------------------
# Permits and documents
# --------------------------------------------------------------------------
def permit_status(item, as_of=None):
    as_of = as_of or date.today()
    status = (item.status or "NOT STARTED").upper()
    if status == "ISSUED" and item.expiry_date and item.expiry_date < as_of:
        return "EXPIRED"
    if status in {"ISSUED", "NOT APPLICABLE"}:
        return status
    if item.required_by_date and item.required_by_date < as_of:
        return "OVERDUE"
    return status


def document_status(item, as_of=None):
    status = (item.status or "NOT STARTED").upper()
    if status in C.DOCUMENT_CLOSED_STATES:
        return status
    if is_overdue(item.required_date, status, C.DOCUMENT_CLOSED_STATES, as_of):
        return "OVERDUE"
    return status


# --------------------------------------------------------------------------
# Acceptance gates
# --------------------------------------------------------------------------
def gate_readiness(items):
    """Readiness percentage of a gate.

    Only ACCEPTED items count as satisfied. NOT APPLICABLE items are excluded
    from the denominator. The gate itself is never marked accepted here --
    formal acceptance is a human decision recorded by a user.
    """
    considered = [i for i in items if (i.status or "").upper() not in C.GATE_ITEM_EXCLUDED]
    if not considered:
        return None, 0, 0
    satisfied = [i for i in considered if (i.status or "").upper() in C.GATE_ITEM_SATISFIED]
    ratio = safe_div(len(satisfied), len(considered))
    percent = None if ratio is None else ratio * 100.0
    return percent, len(satisfied), len(considered)


def gate_derived_state(gate, readiness_pct):
    """Suggested (never automatic) state of a gate."""
    recorded = (gate.status or "NOT STARTED").upper()
    if recorded in {"ACCEPTED", "REJECTED", "SUBMITTED"}:
        return recorded
    if readiness_pct is None:
        return "NOT STARTED"
    if readiness_pct >= 100.0:
        return "READY"
    if readiness_pct > 0.0:
        return "IN PROGRESS"
    return "NOT STARTED"


# --------------------------------------------------------------------------
# Source documents
# --------------------------------------------------------------------------
def document_governs_execution(doc):
    """Whether a source document may govern execution data."""
    return (doc.status or "").upper() in C.DOC_STATUS_AUTHORITATIVE


def document_blocks_import(doc):
    """Draft / reference / reconciliation documents never override approved data."""
    return (doc.status or "").upper() in C.DOC_STATUS_NON_GOVERNING
