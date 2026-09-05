"""Central vocabulary for BASSIGNANA EPC CONTROL.

Every status list, category list and classification used anywhere in the
application is defined here once. Templates and services import from here
rather than repeating literals.
"""
from __future__ import annotations

DATA_REQUIRED = "DATA REQUIRED"
SOURCE_RECONCILIATION_REQUIRED = "SOURCE RECONCILIATION REQUIRED"

# --------------------------------------------------------------------------
# Source documents
# --------------------------------------------------------------------------
DOC_STATUS = [
    "CONTRACTUAL BASELINE",
    "APPROVED",
    "CURRENT WORKING",
    "SUPERSEDED",
    "DRAFT",
    "REFERENCE ONLY",
    "ACTUAL SITE RECORD",
    "REQUIRES RECONCILIATION",
]
# Statuses that may govern execution / be used as an authoritative import source.
DOC_STATUS_AUTHORITATIVE = {"CONTRACTUAL BASELINE", "APPROVED", "CURRENT WORKING"}
# Statuses that must never override approved information.
DOC_STATUS_NON_GOVERNING = {"DRAFT", "REFERENCE ONLY", "SUPERSEDED", "REQUIRES RECONCILIATION"}

DOC_TYPES = [
    "EPC CONTRACT",
    "CONTRACT SCHEDULE",
    "PROGRAMME / SCHEDULE",
    "TECHNICAL SPECIFICATION",
    "GENERAL REPORT",
    "IFC DRAWING",
    "LAYOUT / SITE DATA",
    "BOQ / QUANTITY REGISTER",
    "PERMIT / AUTHORISATION",
    "QA/QC PLAN",
    "ITP / CHECKLIST",
    "TESTING PROTOCOL",
    "ACCEPTANCE PROTOCOL",
    "VENDOR LIST",
    "PROCUREMENT",
    "HSE",
    "DOCUMENT REGISTER",
    "DAILY SITE RECORD",
    "OTHER",
]

# --------------------------------------------------------------------------
# Schedule
# --------------------------------------------------------------------------
SCHEDULE_TYPES = [
    "CONTRACTUAL BASELINE",
    "APPROVED UPDATE",
    "CURRENT WORKING",
    "LOOKAHEAD",
    "RECOVERY PLAN",
    "HISTORICAL",
]
SCHEDULE_STATUS = ["ACTIVE", "SUPERSEDED", "DRAFT", "ARCHIVED"]

SCHEDULE_CLASS_ON_TRACK = "ON TRACK"
SCHEDULE_CLASS_AT_RISK = "AT RISK"
SCHEDULE_CLASS_CRITICAL = "CRITICAL"
SCHEDULE_CLASSES = [SCHEDULE_CLASS_ON_TRACK, SCHEDULE_CLASS_AT_RISK, SCHEDULE_CLASS_CRITICAL]

ACTIVITY_STATUS = ["NOT STARTED", "IN PROGRESS", "COMPLETE", "ON HOLD", "CANCELLED"]

PROGRESS_METHODS = ["QUANTITY", "WEIGHTED", "MANUAL"]
WEIGHT_BASIS = ["APPROVED WEIGHT", "DURATION DERIVED", "QUANTITY", "NOT SET"]

DISCIPLINES = [
    "Civil",
    "Mechanical",
    "Electrical",
    "QA/QC",
    "HSE",
    "Supervision",
    "Logistics",
    "Survey",
    "Commissioning",
    "Engineering",
    "Procurement",
    "Grid / DSO",
    "Other",
]

# --------------------------------------------------------------------------
# Daily site
# --------------------------------------------------------------------------
SHIFTS = ["DAY", "NIGHT", "DAY + NIGHT"]
WEATHER = ["Clear", "Partly cloudy", "Cloudy", "Rain", "Heavy rain", "Fog", "Snow", "Wind", "Storm"]

OBSERVATION_CATEGORIES = [
    "Progress", "Quality", "HSE", "Design", "Drainage", "Civil",
    "Electrical", "Logistics", "Equipment", "Access", "Environmental", "Other",
]
SEVERITIES = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]

EQUIPMENT_STATUS = ["WORKING", "IDLE", "BREAKDOWN", "STANDBY", "OFF SITE"]

# --------------------------------------------------------------------------
# Blockers
# --------------------------------------------------------------------------
BLOCKER_CATEGORIES = [
    "Material", "Equipment", "Workforce", "Weather", "Design", "RFI",
    "Inspection", "Quality", "Permit", "Grid/DSO", "Access", "HSE",
    "Client decision", "Contractor", "Other",
]

# --------------------------------------------------------------------------
# Action-style records (issues, observations, blockers)
# --------------------------------------------------------------------------
ACTION_STATUS = ["OPEN", "IN PROGRESS", "OVERDUE", "CLOSED"]
ACTION_OPEN_STATES = {"OPEN", "IN PROGRESS", "OVERDUE"}
PRIORITIES = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]

ISSUE_CATEGORIES = [
    "Progress", "Quality", "HSE", "Design", "Commercial", "Procurement",
    "Permit", "Grid/DSO", "Client", "Subcontractor", "Other",
]

# --------------------------------------------------------------------------
# Quality
# --------------------------------------------------------------------------
QUALITY_RECORD_TYPES = [
    "INSPECTION", "ITP POINT", "CHECKLIST", "NCR",
    "CORRECTIVE ACTION", "PUNCH LIST", "TEST RECORD",
]
QUALITY_STATUS = [
    "OPEN", "UNDER REVIEW", "ACTION REQUIRED", "READY FOR REINSPECTION",
    "ACCEPTED", "CLOSED", "REJECTED",
]
QUALITY_OPEN_STATES = {"OPEN", "UNDER REVIEW", "ACTION REQUIRED", "READY FOR REINSPECTION", "REJECTED"}
QUALITY_CLOSED_STATES = {"ACCEPTED", "CLOSED"}
INSPECTION_RESULTS = ["", "PASS", "FAIL", "PASS WITH COMMENTS", "NOT INSPECTED"]

INSPECTION_POINT_TYPES = ["HOLD", "WITNESS", "REVIEW", "SURVEILLANCE"]
INSPECTION_TYPES = [
    "Visual inspection", "Dimensional check", "Torque check", "Material receipt",
    "Electrical test", "Mechanical test", "Document review", "Functional test",
    "Thermographic inspection", "Survey check", "Other",
]

# Record-number prefixes keyed by record type.
QUALITY_NUMBER_PREFIX = {
    "NCR": "BAS-NCR",
    "PUNCH LIST": "BAS-PUN",
    "INSPECTION": "BAS-INS",
    "ITP POINT": "BAS-ITP",
    "CHECKLIST": "BAS-CHK",
    "CORRECTIVE ACTION": "BAS-CAR",
    "TEST RECORD": "BAS-TST",
}

# --------------------------------------------------------------------------
# RFI
# --------------------------------------------------------------------------
RFI_STATUS = ["OPEN", "ANSWERED", "CLOSED", "OVERDUE"]
RFI_OPEN_STATES = {"OPEN", "OVERDUE"}

# --------------------------------------------------------------------------
# Procurement
# --------------------------------------------------------------------------
PROCUREMENT_STAGES = [
    "REQUIRED", "RFQ", "TECHNICAL REVIEW", "COMMERCIAL REVIEW", "SELECTED",
    "CONTRACTED/ORDERED", "MANUFACTURING", "FAT", "READY TO SHIP", "SHIPPED",
    "DELIVERED", "INSPECTED", "ACCEPTED", "INSTALLED",
]
PROCUREMENT_STATUS = ["ON TIME", "AT RISK", "LATE", "DELIVERED", "ACCEPTED", "INSTALLED"]
FAT_STATUS = ["NOT REQUIRED", "NOT STARTED", "PLANNED", "IN PROGRESS", "PASSED", "FAILED"]

DELIVERY_STATUS = ["DELIVERED", "INSPECTED", "ACCEPTED", "REJECTED", "PARTIALLY ACCEPTED"]

STOCK_OK = "OK"
STOCK_LOW = "LOW STOCK"
STOCK_SHORTAGE = "SHORTAGE"
STOCK_STATUS = [STOCK_OK, STOCK_LOW, STOCK_SHORTAGE]

MATERIAL_TXN_TYPES = [
    "RECEIPT ACCEPTED", "ISSUE TO WORKFRONT", "INSTALLED IN WORKS",
    "ADJUSTMENT", "RETURN TO STORE",
]
#: Movements that take material out of the store.
MATERIAL_TXN_OUT = {"ISSUE TO WORKFRONT"}
#: Movements that record material fixed in the permanent works. These do not
#: touch store stock: the material left the store when it was issued.
MATERIAL_TXN_INSTALL = {"INSTALLED IN WORKS"}

# --------------------------------------------------------------------------
# Permits / documents
# --------------------------------------------------------------------------
PERMIT_STATUS = [
    "NOT STARTED", "IN PREPARATION", "SUBMITTED", "ISSUED",
    "EXPIRED", "REJECTED", "NOT APPLICABLE",
]
PERMIT_OPEN_STATES = {"NOT STARTED", "IN PREPARATION", "SUBMITTED", "REJECTED", "EXPIRED"}

DOCUMENT_CATEGORIES = [
    "Engineering", "IFC", "Permit", "HSE", "QA/QC", "Procurement",
    "Material Certificate", "FAT", "Test", "Commissioning", "As-Built",
    "Acceptance", "Warranty", "O&M",
]
DOCUMENT_STATUS = [
    "NOT STARTED", "IN PREPARATION", "SUBMITTED", "UNDER REVIEW",
    "ACCEPTED", "REJECTED", "SUPERSEDED", "NOT APPLICABLE",
]
DOCUMENT_CLOSED_STATES = {"ACCEPTED", "NOT APPLICABLE"}

# --------------------------------------------------------------------------
# Acceptance gates
# --------------------------------------------------------------------------
GATE_ITEM_STATUS = [
    "NOT STARTED", "IN PROGRESS", "READY", "SUBMITTED",
    "ACCEPTED", "REJECTED", "NOT APPLICABLE",
]
# Items that count as satisfied for readiness percentage.
GATE_ITEM_SATISFIED = {"ACCEPTED"}
# Items excluded from the readiness denominator.
GATE_ITEM_EXCLUDED = {"NOT APPLICABLE"}
GATE_STATUS = ["NOT STARTED", "IN PROGRESS", "READY", "SUBMITTED", "ACCEPTED", "REJECTED"]

GATES = [
    ("A", "Works Completion", "Schedule 04A - Works Completion Acceptance"),
    ("B", "Commissioning Acceptance", "Schedule 04B - Commissioning Acceptance"),
    ("C", "Provisional Acceptance (PAC)", "Schedule 04C - PAC Acceptance"),
    ("D", "Final Acceptance (FAC)", "Schedule 04D - Final Acceptance"),
]

# --------------------------------------------------------------------------
# Badge colour mapping (single source of truth for templates)
# --------------------------------------------------------------------------
BADGE_CLASS = {
    SCHEDULE_CLASS_ON_TRACK: "bg-success",
    SCHEDULE_CLASS_AT_RISK: "bg-warning text-dark",
    SCHEDULE_CLASS_CRITICAL: "bg-danger",
    "OPEN": "bg-danger",
    "IN PROGRESS": "bg-warning text-dark",
    "IN PREPARATION": "bg-warning text-dark",
    "OVERDUE": "bg-danger",
    "CLOSED": "bg-success",
    "COMPLETE": "bg-success",
    "NOT STARTED": "bg-secondary",
    "ON HOLD": "bg-warning text-dark",
    "CANCELLED": "bg-secondary",
    "UNDER REVIEW": "bg-info text-dark",
    "ACTION REQUIRED": "bg-danger",
    "READY FOR REINSPECTION": "bg-warning text-dark",
    "ACCEPTED": "bg-success",
    "REJECTED": "bg-danger",
    "ANSWERED": "bg-info text-dark",
    "ON TIME": "bg-success",
    "AT RISK": "bg-warning text-dark",
    "LATE": "bg-danger",
    "DELIVERED": "bg-info text-dark",
    "INSPECTED": "bg-info text-dark",
    "INSTALLED": "bg-success",
    STOCK_OK: "bg-success",
    STOCK_LOW: "bg-warning text-dark",
    STOCK_SHORTAGE: "bg-danger",
    "SUBMITTED": "bg-info text-dark",
    "ISSUED": "bg-success",
    "EXPIRED": "bg-danger",
    "NOT APPLICABLE": "bg-secondary",
    "SUPERSEDED": "bg-secondary",
    "READY": "bg-primary",
    "LOW": "bg-secondary",
    "MEDIUM": "bg-info text-dark",
    "HIGH": "bg-warning text-dark",
    "CRITICAL": "bg-danger",
    "CONTRACTUAL BASELINE": "bg-dark",
    "APPROVED": "bg-success",
    "CURRENT WORKING": "bg-primary",
    "DRAFT": "bg-warning text-dark",
    "REFERENCE ONLY": "bg-secondary",
    "ACTUAL SITE RECORD": "bg-info text-dark",
    "REQUIRES RECONCILIATION": "bg-danger",
    "FAILED": "bg-danger",
    "PASSED": "bg-success",
    "PASS": "bg-success",
    "FAIL": "bg-danger",
    "PASS WITH COMMENTS": "bg-warning text-dark",
    "ACTIVE": "bg-success",
    "ARCHIVED": "bg-secondary",
    DATA_REQUIRED: "bg-danger",
}


def badge(value=None):
    """Return the Bootstrap badge class for any status token."""
    if not value:
        return "bg-secondary"
    token = str(value).strip()
    return BADGE_CLASS.get(token.upper(), BADGE_CLASS.get(token, "bg-secondary"))
