"""CSV exporters for every register.

Each exporter returns (filename, csv_text). Filters supplied by the calling
route are preserved wherever the underlying register supports them.
"""
from __future__ import annotations

import csv
import io
from datetime import date, datetime

from app.models import (
    AcceptanceGate,
    AcceptanceGateItem,
    ActivityQuantity,
    Area,
    Blocker,
    DailyProgress,
    Delivery,
    DocumentRegisterItem,
    EquipmentEntry,
    InspectionRequirement,
    Issue,
    Material,
    PaymentMilestone,
    PermitItem,
    ProcurementPackage,
    QualityRecord,
    Rfi,
    SiteObservation,
    SourceDocument,
    WorkforceEntry,
)
from app.services import (
    commercial_service,
    procurement_service,
    progress,
    registers,
    schedule_service,
)
from app.services.status_rules import document_status, permit_status, quality_status, rfi_status


def _fmt(value):
    if value is None:
        return ""
    if isinstance(value, (date, datetime)):
        return value.isoformat()[:10] if isinstance(value, date) and not isinstance(value, datetime) \
            else value.isoformat(sep=" ", timespec="minutes")
    if isinstance(value, bool):
        return "YES" if value else "NO"
    if isinstance(value, float):
        return f"{value:.4f}".rstrip("0").rstrip(".")
    return str(value)


def _csv(headers, rows):
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(headers)
    for row in rows:
        writer.writerow([_fmt(v) for v in row])
    return buffer.getvalue()


def _stamp(name):
    return f"bassignana_{name}_{date.today():%Y-%m-%d}.csv"


# --------------------------------------------------------------------------
def export_schedule(as_of=None, **_):
    rows = schedule_service.comparison_rows(as_of)
    headers = [
        "WBS", "Activity", "Work package", "Discipline", "Milestone",
        "Baseline start", "Baseline finish", "Current start", "Current finish",
        "Actual start", "Actual finish", "Planned %", "Actual %", "Actual basis",
        "Variance (pp)", "Contractual variance (pp)", "Start delay days",
        "Finish delay days", "Classification", "Status", "Baseline match",
    ]
    data = [[
        r["wbs_code"], r["name"], r["work_package"], r["discipline"], r["is_milestone"],
        r["baseline_start"], r["baseline_finish"], r["plan_start"], r["plan_finish"],
        r["actual_start"], r["actual_finish"], r["planned_pct"], r["actual_pct"],
        r["actual_basis"], r["variance"], r["contractual_variance"],
        r["start_delay_days"], r["finish_delay_days"], r["classification"],
        r["status"], r["match_kind"],
    ] for r in rows]
    return _stamp("schedule_wbs"), _csv(headers, data)


def export_daily_progress(date_from=None, date_to=None, **_):
    query = DailyProgress.query
    if date_from:
        query = query.filter(DailyProgress.entry_date >= date_from)
    if date_to:
        query = query.filter(DailyProgress.entry_date <= date_to)
    rows = query.order_by(DailyProgress.entry_date, DailyProgress.wbs_code).all()
    headers = [
        "Date", "Report", "WBS", "Activity", "Work package", "Area", "Unit",
        "Planned qty", "Actual qty", "Achievement %", "Cumulative before",
        "Cumulative after", "Total required", "Completion %", "Workers", "Hours",
        "Qty/worker-day", "Qty/worker-hour", "Activity affected", "Blocker category",
        "Estimated lost hours", "Comments",
    ]
    data = [[
        r.entry_date, r.report.report_number if r.report else "", r.wbs_code, r.activity_name,
        r.work_package, r.area.label if r.area else "", r.unit, r.planned_quantity,
        r.actual_quantity, r.achievement_pct, r.cumulative_before, r.cumulative_after,
        r.total_required_quantity, r.completion_pct, r.workers, r.hours,
        r.quantity_per_worker_day, r.quantity_per_worker_hour, r.activity_affected,
        r.blocker_category, r.estimated_lost_hours, r.comments,
    ] for r in rows]
    return _stamp("daily_progress"), _csv(headers, data)


def export_workforce(date_from=None, date_to=None, **_):
    query = WorkforceEntry.query
    if date_from:
        query = query.filter(WorkforceEntry.entry_date >= date_from)
    if date_to:
        query = query.filter(WorkforceEntry.entry_date <= date_to)
    rows = query.order_by(WorkforceEntry.entry_date, WorkforceEntry.discipline).all()
    headers = ["Date", "Contractor", "Discipline", "Work package", "Area",
               "Workers", "Hours", "Overtime", "Man-hours", "Comments"]
    data = [[
        r.entry_date, r.contractor.name if r.contractor else r.contractor_name,
        r.discipline, r.work_package, r.area.label if r.area else "",
        r.workers, r.hours, r.overtime_hours, r.man_hours, r.comments,
    ] for r in rows]
    return _stamp("workforce"), _csv(headers, data)


def export_equipment(date_from=None, date_to=None, **_):
    query = EquipmentEntry.query
    if date_from:
        query = query.filter(EquipmentEntry.entry_date >= date_from)
    if date_to:
        query = query.filter(EquipmentEntry.entry_date <= date_to)
    rows = query.order_by(EquipmentEntry.entry_date, EquipmentEntry.equipment_type).all()
    headers = ["Date", "Equipment", "Owner", "Contractor", "Area", "Quantity", "Status",
               "Working hours", "Idle hours", "Breakdown hours", "Utilisation %",
               "Reason", "Comments"]
    data = [[
        r.entry_date, r.equipment_type, r.owner,
        r.contractor.name if r.contractor else "", r.area.label if r.area else "",
        r.quantity, r.status, r.working_hours, r.idle_hours, r.breakdown_hours,
        r.utilisation_pct, r.reason, r.comments,
    ] for r in rows]
    return _stamp("equipment"), _csv(headers, data)


def export_blockers(date_from=None, date_to=None, **_):
    query = Blocker.query
    if date_from:
        query = query.filter(Blocker.entry_date >= date_from)
    if date_to:
        query = query.filter(Blocker.entry_date <= date_to)
    rows = query.order_by(Blocker.entry_date.desc()).all()
    headers = ["Number", "Date", "WBS", "Area", "Activity", "Category", "Description",
               "Start", "End", "Estimated lost hours", "Actual lost hours",
               "Workers affected", "Equipment affected", "Lost man-hours",
               "Responsible", "Status", "Action", "Comments"]
    data = [[
        r.blocker_number, r.entry_date, r.wbs_code, r.area.label if r.area else "",
        r.activity, r.category, r.description, r.start_datetime, r.end_datetime,
        r.estimated_lost_hours, r.actual_lost_hours, r.workers_affected,
        r.equipment_affected, r.lost_man_hours, r.responsible_party, r.status,
        r.action, r.comments,
    ] for r in rows]
    return _stamp("blockers"), _csv(headers, data)


def export_issues(**_):
    rows = Issue.query.order_by(Issue.date_raised.desc()).all()
    headers = ["Number", "Raised", "Title", "Category", "WBS", "Area", "Priority",
               "Raised by", "Responsible", "Target date", "Status", "Action",
               "Closed", "Comments"]
    data = [[
        r.issue_number, r.date_raised, r.title, r.category, r.wbs_code,
        r.area.label if r.area else "", r.priority, r.raised_by, r.responsible_party,
        r.target_date, r.status, r.action, r.closed_date, r.comments,
    ] for r in rows]
    return _stamp("issues_actions"), _csv(headers, data)


def export_quality(record_type=None, **_):
    rows = registers.quality_query(record_type=record_type)
    headers = ["Number", "Type", "Date", "WBS", "Work package", "Area", "Discipline",
               "Title", "Description", "Specification", "Drawing", "ITP reference",
               "Responsible", "Severity", "Target closure", "Status", "Derived status",
               "Inspection result", "Corrective action", "Evidence", "Closure date",
               "Gate", "Comments"]
    data = [[
        r.record_number, r.record_type, r.record_date, r.wbs_code, r.work_package,
        r.area.label if r.area else "", r.discipline, r.title, r.description,
        r.specification_reference, r.drawing_reference, r.itp_reference,
        r.responsible_party, r.severity, r.target_closure_date, r.status,
        quality_status(r), r.inspection_result, r.corrective_action,
        r.evidence_reference, r.closure_date, r.gate_code, r.comments,
    ] for r in rows]
    name = f"quality_{(record_type or 'all').lower().replace(' ', '_')}"
    return _stamp(name), _csv(headers, data)


def export_rfis(**_):
    rows = Rfi.query.order_by(Rfi.date_raised.desc()).all()
    headers = ["Number", "Raised", "Raised by", "Area", "WBS", "Discipline", "Subject",
               "Question", "Reference", "Responsible", "Required response",
               "Response date", "Status", "Derived status", "Response",
               "Schedule impact", "Estimated delay days", "Linked blocker", "Comments"]
    data = [[
        r.rfi_number, r.date_raised, r.raised_by, r.area.label if r.area else "",
        r.wbs_code, r.discipline, r.subject, r.question, r.reference,
        r.responsible_party, r.required_response_date, r.response_date, r.status,
        rfi_status(r), r.response, r.schedule_impact, r.estimated_delay_days,
        r.blocker.blocker_number if r.blocker else "", r.comments,
    ] for r in rows]
    return _stamp("rfis"), _csv(headers, data)


def export_procurement(**_):
    views = procurement_service.all_package_views()
    headers = ["Package code", "Package", "Category", "Equipment", "Approved vendors",
               "Stage", "Status", "WBS", "PO reference", "Planned delivery",
               "Forecast delivery", "Actual delivery", "FAT required", "FAT status",
               "FAT date", "Material lines", "Late lines", "Shortage lines", "Comments"]
    data = [[
        v["package"].package_code, v["package"].package_name, v["package"].category,
        v["package"].equipment, v["package"].approved_vendors, v["package"].stage,
        v["status"], v["package"].wbs_code, v["package"].po_reference,
        v["package"].planned_delivery, v["package"].forecast_delivery,
        v["package"].actual_delivery, v["package"].fat_required, v["package"].fat_status,
        v["package"].fat_date, len(v["materials"]), v["late_count"], v["shortage_count"],
        v["package"].comments,
    ] for v in views]
    return _stamp("procurement_packages"), _csv(headers, data)


def export_materials(**_):
    rows = Material.query.order_by(Material.package_id, Material.item).all()
    headers = ["Package", "Item", "Manufacturer", "Vendor", "Approved vendor", "Unit",
               "Contract qty", "Required", "Ordered", "Manufactured", "Delivered",
               "Accepted", "Installed", "Available stock", "Stock status",
               "Procurement status", "PO reference", "FAT required", "FAT status",
               "Planned delivery", "Forecast delivery", "Actual delivery",
               "Delivery note", "Material certificate", "Allocated area", "Comments"]
    data = []
    for material in rows:
        view = procurement_service.material_view(material)
        data.append([
            material.package.package_code if material.package else "", material.item,
            material.manufacturer, material.vendor, material.approved_vendor, material.unit,
            material.contract_quantity, material.total_required, material.ordered,
            material.manufactured, material.delivered, material.accepted, material.installed,
            view["available"], view["stock_status"], view["procurement_status"],
            material.po_reference, material.fat_required, material.fat_status,
            material.planned_delivery, material.forecast_delivery, material.actual_delivery,
            material.delivery_note_reference, material.material_certificate_reference,
            material.allocated_area.label if material.allocated_area else "", material.comments,
        ])
    return _stamp("materials"), _csv(headers, data)


def export_deliveries(date_from=None, date_to=None, **_):
    query = Delivery.query
    if date_from:
        query = query.filter(Delivery.delivery_date >= date_from)
    if date_to:
        query = query.filter(Delivery.delivery_date <= date_to)
    rows = query.order_by(Delivery.delivery_date.desc()).all()
    headers = ["Date", "Package", "Material", "Delivery note", "Quantity", "Unit",
               "Status", "Accepted qty", "Rejected qty", "Inspection date",
               "Inspected by", "Certificate", "Area", "Comments"]
    data = [[
        r.delivery_date, r.package.package_code if r.package else "",
        r.material.item if r.material else "", r.delivery_note_reference, r.quantity,
        r.unit, r.status, r.accepted_quantity, r.rejected_quantity, r.inspection_date,
        r.inspected_by, r.certificate_reference, r.area.label if r.area else "", r.comments,
    ] for r in rows]
    return _stamp("deliveries"), _csv(headers, data)


def export_permits(**_):
    rows = PermitItem.query.order_by(PermitItem.required_by_date).all()
    headers = ["Item", "Authority", "Responsibility", "Required for", "Required by",
               "Issued", "Expiry", "Recorded status", "Derived status",
               "Document reference", "Verified", "Blocker impact", "Comments"]
    data = [[
        r.item_name, r.authority, r.responsibility, r.required_for, r.required_by_date,
        r.issued_date, r.expiry_date, r.status, permit_status(r), r.document_reference,
        r.verified, r.blocker_impact, r.comments,
    ] for r in rows]
    return _stamp("permits"), _csv(headers, data)


def export_acceptance(**_):
    headers = ["Gate", "Gate name", "Item code", "Item", "Category", "Description",
               "Responsible", "Target date", "Actual date", "Status", "Evidence",
               "Contract reference", "Comments"]
    data = []
    for gate in AcceptanceGate.query.order_by(AcceptanceGate.sequence).all():
        for item in gate.items:
            data.append([
                gate.gate_code, gate.name, item.item_code, item.item_name, item.category,
                item.description, item.responsible_party, item.target_date, item.actual_date,
                item.status, item.evidence_reference, item.contract_reference, item.comments,
            ])
    return _stamp("acceptance_register"), _csv(headers, data)


def export_documents(**_):
    rows = DocumentRegisterItem.query.order_by(
        DocumentRegisterItem.category, DocumentRegisterItem.title).all()
    headers = ["Number", "Title", "Category", "Discipline", "WBS", "Revision",
               "Recorded status", "Derived status", "Issue date", "Required date",
               "Submitted", "Accepted", "Gate", "Mandatory", "Folder", "Source path",
               "Remarks"]
    data = [[
        r.document_number, r.title, r.category, r.discipline, r.wbs_code, r.revision,
        r.status, document_status(r), r.issue_date, r.required_date, r.submitted_date,
        r.accepted_date, r.gate_code, r.mandatory, r.folder_path, r.source_path, r.remarks,
    ] for r in rows]
    return _stamp("document_register"), _csv(headers, data)


def export_areas(**_):
    rows = Area.query.order_by(Area.area_code).all()
    headers = ["Area code", "Area name", "Description", "Parent area", "Drawing reference",
               "IFC revision", "Active", "Source document"]
    data = [[
        r.area_code, r.area_name, r.description, r.parent.area_code if r.parent else "",
        r.drawing_reference, r.ifc_revision, r.active,
        r.source_document.label if r.source_document else "",
    ] for r in rows]
    return _stamp("areas"), _csv(headers, data)


def export_quantities(**_):
    rows = ActivityQuantity.query.order_by(ActivityQuantity.wbs_code, ActivityQuantity.item).all()
    headers = ["WBS", "Area", "Activity", "Item", "Total quantity", "Unit",
               "Source document", "Source reference", "Revision", "Notes"]
    data = [[
        r.wbs_code, r.area.label if r.area else "", r.activity_name, r.item,
        r.total_quantity, r.unit, r.source_document.label if r.source_document else "",
        r.source_reference, r.revision, r.notes,
    ] for r in rows]
    return _stamp("quantities_boq"), _csv(headers, data)


def export_inspection_requirements(**_):
    rows = InspectionRequirement.query.order_by(
        InspectionRequirement.wbs_code, InspectionRequirement.itp_reference).all()
    headers = ["WBS", "Work package", "ITP reference", "Inspection type", "Point type",
               "Required evidence", "Acceptance criterion", "Specification", "Discipline",
               "Active", "Source document"]
    data = [[
        r.wbs_code, r.work_package, r.itp_reference, r.inspection_type, r.point_type,
        r.required_evidence, r.acceptance_criterion, r.applicable_specification,
        r.discipline, r.active, r.source_document.label if r.source_document else "",
    ] for r in rows]
    return _stamp("itp_requirements"), _csv(headers, data)


def export_observations(date_from=None, date_to=None, **_):
    query = SiteObservation.query
    if date_from:
        query = query.filter(SiteObservation.entry_date >= date_from)
    if date_to:
        query = query.filter(SiteObservation.entry_date <= date_to)
    rows = query.order_by(SiteObservation.entry_date.desc()).all()
    headers = ["Date", "Area", "WBS", "Category", "Severity", "Observation",
               "Action required", "Responsible", "Target date", "Status", "Closed"]
    data = [[
        r.entry_date, r.area.label if r.area else "", r.wbs_code, r.category, r.severity,
        r.observation, r.action_required, r.responsible_party, r.target_date, r.status,
        r.closed_date,
    ] for r in rows]
    return _stamp("site_observations"), _csv(headers, data)


def export_source_documents(**_):
    rows = SourceDocument.query.order_by(SourceDocument.document_type, SourceDocument.title).all()
    headers = ["Type", "Title", "Filename", "Revision", "Document date", "Effective date",
               "Status", "Contractual", "Supersedes", "Source reference", "Imported at", "Notes"]
    data = [[
        r.document_type, r.title, r.source_filename, r.revision, r.document_date,
        r.effective_date, r.status, r.contractual,
        r.supersedes.title if r.supersedes else "", r.source_reference, r.imported_at, r.notes,
    ] for r in rows]
    return _stamp("source_documents"), _csv(headers, data)



def export_payments(**_):
    data = commercial_service.summary()
    headers = ["Seq", "Code", "Description", "Percentage", "Amount", "Currency", "WBS",
               "Gate", "Package", "Planned", "Forecast", "Achieved", "Certified",
               "Invoiced", "Paid", "Recorded status", "Derived status", "Evidence",
               "Comments"]
    rows = []
    for view in data["views"]:
        row = view["milestone"]
        rows.append([
            row.sequence, row.milestone_code, row.description, row.percentage,
            view["amount"], data["currency"], row.wbs_code, row.gate_code,
            row.package_code, row.planned_date, row.forecast_date, row.achieved_date,
            row.certified_date, row.invoiced_date, row.paid_date, row.status,
            view["derived_status"], row.evidence_reference, row.comments,
        ])
    return _stamp("payment_milestones"), _csv(headers, rows)

EXPORTS = {
    "schedule": ("WBS / Schedule", export_schedule),
    "daily_progress": ("Daily Progress", export_daily_progress),
    "workforce": ("Workforce", export_workforce),
    "equipment": ("Equipment", export_equipment),
    "blockers": ("Blockers", export_blockers),
    "issues": ("Issues / Actions", export_issues),
    "quality": ("Quality (all record types)", export_quality),
    "rfis": ("RFIs", export_rfis),
    "procurement": ("Procurement packages", export_procurement),
    "materials": ("Materials", export_materials),
    "deliveries": ("Deliveries", export_deliveries),
    "permits": ("Permits / Readiness", export_permits),
    "acceptance": ("Testing / Acceptance register", export_acceptance),
    "documents": ("Document register", export_documents),
    "payments": ("Payment milestones", export_payments),
    "areas": ("Areas / Workfronts", export_areas),
    "quantities": ("Quantities / BOQ", export_quantities),
    "itp": ("ITP requirements", export_inspection_requirements),
    "observations": ("Site observations", export_observations),
    "source_documents": ("Source document register", export_source_documents),
}
