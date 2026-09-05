"""DATA REQUIRED reporting.

The application must never fill a gap in the Bassignana source data with an
assumption. Instead it states exactly which input is missing and which
document would supply it.
"""
from __future__ import annotations

from app import constants as C
from app.models import (
    AcceptanceGate,
    Area,
    ActivityQuantity,
    InspectionRequirement,
    PaymentMilestone,
    PermitItem,
    ProcurementPackage,
    Project,
    ScheduleVersion,
    SourceDocument,
    WbsActivity,
)
from app.services import progress

#: Checks are ordered by setup wizard step.
CHECKS = [
    {
        "key": "project_identity",
        "step": 1,
        "label": "Project identity",
        "mandatory": True,
        "required_input": "Signed EPC Contract (parties, contract reference, Notice to Proceed date)",
    },
    {
        "key": "source_documents",
        "step": 2,
        "label": "Authoritative source documents registered",
        "mandatory": True,
        "required_input": "Signed EPC Contract, Schedules 01/02/03/04/04A-04D, Autorizzazione Unica, "
                          "approved IFC layout",
    },
    {
        "key": "contractual_schedule",
        "step": 3,
        "label": "Contractual baseline schedule",
        "mandatory": True,
        "required_input": "Schedule 03 - Project Timeline (contractual baseline) as CSV/XLSX",
    },
    {
        "key": "working_schedule",
        "step": 4,
        "label": "Current working schedule",
        "mandatory": False,
        "required_input": "Latest approved/updated programme as CSV/XLSX "
                          "(structured export, not a Gantt PDF)",
    },
    {
        "key": "quantities",
        "step": 5,
        "label": "WBS quantities / BOQ",
        "mandatory": True,
        "required_input": "Approved BOQ or quantity register with WBS, unit and total required quantity",
    },
    {
        "key": "areas",
        "step": 6,
        "label": "Project areas / workfronts",
        "mandatory": True,
        "required_input": "Approved IFC / general layout area and workfront coding register",
    },
    {
        "key": "procurement",
        "step": 7,
        "label": "Procurement packages",
        "mandatory": True,
        "required_input": "Procurement package register (Schedule 12 / 18 vendor families, PO status)",
    },
    {
        "key": "quality",
        "step": 8,
        "label": "Quality / ITP requirements",
        "mandatory": True,
        "required_input": "Approved Bassignana QA/QC Plan, ITPs, checklists and hold/witness points",
    },
    {
        "key": "acceptance",
        "step": 8,
        "label": "Acceptance gate checklists",
        "mandatory": False,
        "required_input": "Schedules 04A / 04B / 04C / 04D acceptance prerequisites",
    },
    {
        "key": "permits",
        "step": 8,
        "label": "Permit / readiness register",
        "mandatory": False,
        "required_input": "Verified live Bassignana permit register "
                          "(Schedule 05 requires reconciliation before use)",
    },
    {
        "key": "contract_commercials",
        "step": 1,
        "label": "Contract Price and contractual parameters",
        "mandatory": False,
        "required_input": "Contract Price, delay liquidated damages rate and cap, and the "
                          "adverse-weather thresholds from the signed EPC Contract",
    },
    {
        "key": "payments",
        "step": 7,
        "label": "Payment milestone schedule",
        "mandatory": False,
        "required_input": "Schedule 10 payment milestones (percentages must total 100%)",
    },
    {
        "key": "progress_weights",
        "step": 9,
        "label": "Approved progress weights",
        "mandatory": False,
        "required_input": "Approved progress-weight register (otherwise rollup uses a "
                          "duration-derived basis, clearly labelled)",
    },
]


def _counts():
    project = Project.query.first()
    return {
        "project": project,
        "source_documents": SourceDocument.query.count(),
        "contractual_docs": SourceDocument.query.filter_by(status="CONTRACTUAL BASELINE").count(),
        "baseline_versions": ScheduleVersion.query.filter_by(is_contractual_baseline=True).count(),
        "working_versions": ScheduleVersion.query.filter_by(is_current_working=True).count(),
        "activities": WbsActivity.query.count(),
        "quantities": ActivityQuantity.query.count(),
        "areas": Area.query.filter_by(active=True).count(),
        "packages": ProcurementPackage.query.count(),
        "inspections": InspectionRequirement.query.count(),
        "gates_with_items": sum(1 for g in AcceptanceGate.query.all() if g.items),
        "permits": PermitItem.query.count(),
        "payments": PaymentMilestone.query.count(),
        "payment_pct": sum(float(m.percentage or 0.0)
                           for m in PaymentMilestone.query.all()),
        "approved_weights": WbsActivity.query.filter(
            WbsActivity.weight_basis == "APPROVED WEIGHT",
            WbsActivity.progress_weight.isnot(None),
        ).count(),
    }


def _satisfied(key, counts):
    project = counts["project"]
    if key == "project_identity":
        return bool(project and project.client and project.epc_contractor and project.ntp_date)
    if key == "source_documents":
        return counts["source_documents"] > 0 and counts["contractual_docs"] > 0
    if key == "contractual_schedule":
        return counts["baseline_versions"] > 0 and counts["activities"] > 0
    if key == "working_schedule":
        return counts["working_versions"] > 0
    if key == "quantities":
        return counts["quantities"] > 0
    if key == "areas":
        return counts["areas"] > 0
    if key == "procurement":
        return counts["packages"] > 0
    if key == "quality":
        return counts["inspections"] > 0
    if key == "acceptance":
        return counts["gates_with_items"] >= 4
    if key == "permits":
        return counts["permits"] > 0
    if key == "progress_weights":
        return counts["approved_weights"] > 0
    if key == "contract_commercials":
        return bool(project and project.contract_price and project.delay_lds_pct_per_day)
    if key == "payments":
        return counts["payments"] > 0 and abs(counts["payment_pct"] - 100.0) < 0.01
    return False


def report():
    """Full DATA REQUIRED report used by setup, dashboard and validation."""
    counts = _counts()
    checks = []
    for check in CHECKS:
        satisfied = _satisfied(check["key"], counts)
        checks.append({
            **check,
            "satisfied": satisfied,
            "message": None if satisfied else f"{C.DATA_REQUIRED}: {check['required_input']}",
        })
    missing_mandatory = [i for i in checks if i["mandatory"] and not i["satisfied"]]
    missing_optional = [i for i in checks if not i["mandatory"] and not i["satisfied"]]
    return {
        "checks": checks,
        "counts": counts,
        "missing_mandatory": missing_mandatory,
        "missing_optional": missing_optional,
        "ready": not missing_mandatory,
        "satisfied_count": sum(1 for i in checks if i["satisfied"]),
        "total_count": len(checks),
    }


def reconciliation_flags():
    """Source documents that the project pack marks as needing reconciliation."""
    docs = SourceDocument.query.filter(
        SourceDocument.status.in_(["REQUIRES RECONCILIATION", "DRAFT", "REFERENCE ONLY"])
    ).order_by(SourceDocument.title).all()
    return [{
        "document": d,
        "message": f"{C.SOURCE_RECONCILIATION_REQUIRED}: {d.title}"
                   if d.status == "REQUIRES RECONCILIATION"
                   else f"{d.title} is registered as {d.status} and must not govern execution data.",
    } for d in docs]


def schedule_health():
    """Warnings about the registered schedule versions."""
    warnings = []
    baseline = progress.baseline_version()
    current = progress.current_version()
    if baseline is None:
        warnings.append(f"{C.DATA_REQUIRED}: contractual baseline programme (Schedule 03).")
    if current is None:
        warnings.append(f"{C.DATA_REQUIRED}: current working programme.")
    if baseline is not None and current is not None and baseline.id == current.id:
        warnings.append(
            "No separate current working programme is registered. The contractual baseline "
            "is being shown for operational planning as well."
        )
    if baseline is not None and not baseline.locked:
        warnings.append(
            "The contractual baseline is not locked. Lock it in Schedule & WBS to protect "
            "contractual dates from being edited."
        )
    return warnings
