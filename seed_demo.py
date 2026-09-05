#!/usr/bin/env python3
"""Optional demonstration data for BASSIGNANA EPC CONTROL.

This script exists so the application can be shown working before the real
Bassignana master data is loaded. It writes to a SEPARATE demonstration
database (data/bassignana_demo.db) and never touches data/bassignana.db, so
demonstration records can never be mistaken for, or mixed with, live project
records.

Everything it creates is prefixed DEMO and is fictitious.

    python seed_demo.py                 build the demo database
    python seed_demo.py --run           build it and start the app against it
    python seed_demo.py --reset         delete and rebuild the demo database

To start the application against the demo database afterwards:

    Windows PowerShell:
        $env:BASSIGNANA_DATABASE_URI = "sqlite:///" + (Resolve-Path data/bassignana_demo.db).Path.Replace('\\','/')
        python run.py
    Linux / macOS:
        BASSIGNANA_DATABASE_URI="sqlite:///$(pwd)/data/bassignana_demo.db" python run.py
"""
from __future__ import annotations

import argparse
import random
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DEMO_DB = BASE_DIR / "data" / "bassignana_demo.db"
DEMO_URI = f"sqlite:///{DEMO_DB.as_posix()}"

PREFIX = "DEMO"
random.seed(20260904)


def build_config():
    from app.config import Config

    class DemoConfig(Config):
        SQLALCHEMY_DATABASE_URI = DEMO_URI

    return DemoConfig


def seed():
    from app import create_app
    from app.extensions import db
    from app.models import (
        AcceptanceGate,
        AcceptanceGateItem,
        ActivityQuantity,
        Area,
        Blocker,
        Contractor,
        DailyProgress,
        DailySiteReport,
        Delivery,
        DocumentRegisterItem,
        EquipmentEntry,
        InspectionRequirement,
        Material,
        MaterialTransaction,
        PaymentMilestone,
        PermitItem,
        ProcurementPackage,
        Project,
        QualityRecord,
        Rfi,
        ScheduleVersion,
        SiteObservation,
        SourceDocument,
        WbsActivity,
        WorkforceEntry,
    )
    from app.services import numbering

    app = create_app(build_config())
    with app.app_context():
        if SourceDocument.query.filter(SourceDocument.title.like(f"{PREFIX}%")).first():
            print("The demo database already contains demonstration data. "
                  "Use --reset to rebuild it.")
            return app

        today = date.today()
        project = Project.query.first()
        project.name = f"{PREFIX} Bassignana Solar 2"
        project.subtitle = "DEMONSTRATION DATA - not the live project record"
        project.plant_name = f"{PREFIX} plant"
        project.client = f"{PREFIX} Client S.r.l."
        project.epc_contractor = f"{PREFIX} EPC Contractor SpA"
        project.contract_reference = f"{PREFIX}-EPC-0001"
        project.ntp_date = today - timedelta(days=120)
        project.comune, project.provincia, project.regione = "Demo", "Demo", "Demo"
        project.nominal_dc_kwp = 8169.525
        project.grid_voltage_kv = 15.0
        project.dso = f"{PREFIX} DSO"
        project.contract_price = 4800000.0
        project.currency = "EUR"
        project.advance_payment_pct = 15.0
        project.performance_bond_pct = 10.0
        project.delay_lds_pct_per_day = 0.15
        project.delay_lds_cap_pct = 10.0
        project.delay_termination_days = 60
        project.dnp_months = 24
        project.min_availability_pct = 98.0
        project.guaranteed_pr_note = "design performance ratio less 1.00%"
        project.adverse_wind_ms = 30.0
        project.adverse_rain_mm_h = 10.0
        project.notes = ("Demonstration records only. Delete this database before using the "
                         "application for the live project.")

        # ---- source documents -------------------------------------------
        baseline_doc = SourceDocument(
            document_type="PROGRAMME / SCHEDULE", title=f"{PREFIX} Contractual programme",
            revision="R0", document_date=today - timedelta(days=120),
            status="CONTRACTUAL BASELINE", contractual=True,
            notes="Demonstration document.")
        working_doc = SourceDocument(
            document_type="PROGRAMME / SCHEDULE", title=f"{PREFIX} Working programme",
            revision="R1", document_date=today - timedelta(days=30),
            status="CURRENT WORKING", notes="Demonstration document.")
        layout_doc = SourceDocument(
            document_type="IFC DRAWING", title=f"{PREFIX} General layout",
            revision="A", status="APPROVED", notes="Demonstration document.")
        db.session.add_all([baseline_doc, working_doc, layout_doc])
        db.session.flush()

        baseline = ScheduleVersion(
            name=f"{PREFIX} Contractual programme", revision="R0",
            schedule_type="CONTRACTUAL BASELINE", issue_date=today - timedelta(days=120),
            effective_date=today - timedelta(days=120), is_contractual_baseline=True,
            locked=True, source_document_id=baseline_doc.id)
        working = ScheduleVersion(
            name=f"{PREFIX} Working programme", revision="R1",
            issue_date=today - timedelta(days=30), effective_date=today - timedelta(days=30),
            schedule_type="CURRENT WORKING", is_current_working=True,
            source_document_id=working_doc.id)
        db.session.add_all([baseline, working])
        db.session.flush()

        # ---- WBS ---------------------------------------------------------
        # (wbs, name, work package, discipline, offset start, duration, slip,
        #  unit, total quantity, reported %)
        SPEC = [
            ("1", "DEMO PV PLANT", None, None, -120, 300, 0, None, None, None),
            ("1.1", "Pre-construction", "Pre-construction", "Engineering", -120, 90, 0, None, None, 100.0),
            ("1.1.1", "Executive design", "Pre-construction", "Engineering", -120, 60, 10, None, None, 90.0),
            ("1.1.2", "Geological investigations", "Pre-construction", "Survey", -110, 15, 0, None, None, 100.0),
            ("1.2", "Site set-up", "Mobilisation", "Civil", -60, 40, 5, None, None, 80.0),
            ("1.2.1", "Terrain levelling and grading", "Mobilisation", "Civil", -60, 20, 5, "m3", 56798.07, None),
            ("1.2.2", "Drainage system works", "Mobilisation", "Civil", -45, 20, 8, "m", 3200.0, None),
            ("1.2.3", "Perimeter roads and site access", "Mobilisation", "Civil", -35, 15, 6, "m", 2400.0, None),
            ("1.3", "PV plant construction", "PV Construction", "Mechanical", -30, 120, 20, None, None, None),
            ("1.3.1", "Foundation piles ramming", "PV Mechanical Works", "Mechanical", -30, 40, 12, "no", 5200.0, None),
            ("1.3.2", "Mounting structure installation", "PV Mechanical Works", "Mechanical", -5, 45, 15, "no", 341.0, None),
            ("1.3.3", "PV module installation", "PV Mechanical Works", "Mechanical", 10, 40, 18, "no", 13965.0, None),
            ("1.3.4", "DC string cabling", "PV Electrical Works", "Electrical", 20, 40, 18, "no", 537.0, None),
            ("1.3.5", "MV trenches and ducting", "PV Civil Works", "Civil", 5, 45, 10, "m", 6800.0, None),
            ("1.4", "Cold commissioning", "Testing & Commissioning", "Commissioning", 120, 40, 25, None, None, 0.0),
            ("1.5", "Energisation", "Testing & Commissioning", "Commissioning", 165, 0, 30, None, None, 0.0),
            ("1.6", "Provisional acceptance", "Acceptance", "Commissioning", 175, 0, 35, None, None, 0.0),
        ]
        for index, (wbs, name, package, discipline, offset, duration, slip,
                    unit, quantity, reported) in enumerate(SPEC, start=1):
            base_start = today + timedelta(days=offset)
            base_finish = base_start + timedelta(days=duration)
            for version, start, finish in (
                (baseline, base_start, base_finish),
                (working, base_start + timedelta(days=slip), base_finish + timedelta(days=slip)),
            ):
                activity = WbsActivity(
                    schedule_version_id=version.id, wbs_code=wbs,
                    parent_wbs_code=wbs.rsplit(".", 1)[0] if "." in wbs else None,
                    activity_name=name, work_package=package, discipline=discipline,
                    level=wbs.count(".") + 1, sort_index=index,
                    plan_start=start, plan_finish=finish, duration_days=duration,
                    is_milestone=duration == 0, unit=unit,
                    total_required_quantity=quantity,
                    progress_method="QUANTITY" if quantity else "MANUAL",
                    reported_completion_pct=reported or 0.0,
                    source_document_id=version.source_document_id,
                )
                if version.is_contractual_baseline:
                    activity.baseline_start, activity.baseline_finish = start, finish
                db.session.add(activity)
        db.session.flush()

        # ---- areas -------------------------------------------------------
        areas = []
        for code, name in [("D-A", "Demo sub-field A"), ("D-B", "Demo sub-field B"),
                           ("D-C", "Demo sub-field C"), ("D-SUB", "Demo substation compound")]:
            row = Area(area_code=f"{PREFIX}-{code}", area_name=f"{PREFIX} {name}",
                       drawing_reference=f"{PREFIX}-LAYOUT-01", ifc_revision="A",
                       source_document_id=layout_doc.id)
            db.session.add(row)
            areas.append(row)
        db.session.flush()

        # ---- contractors --------------------------------------------------
        contractors = []
        for name, role, discipline in [
            (f"{PREFIX} EPC Contractor SpA", "EPC CONTRACTOR", "Supervision"),
            (f"{PREFIX} Civil Sub Srl", "SUBCONTRACTOR", "Civil"),
            (f"{PREFIX} Electrical Sub Srl", "SUBCONTRACTOR", "Electrical"),
            (f"{PREFIX} Piling Sub Srl", "SUBCONTRACTOR", "Mechanical"),
        ]:
            row = Contractor(name=name, role=role, discipline=discipline)
            db.session.add(row)
            contractors.append(row)
        db.session.flush()

        # ---- quantities ---------------------------------------------------
        for wbs, item, quantity, unit in [
            ("1.2.1", f"{PREFIX} earthworks cut", 56798.07, "m3"),
            ("1.3.1", f"{PREFIX} foundation piles", 5200, "no"),
            ("1.3.3", f"{PREFIX} PV modules", 13965, "no"),
            ("1.3.4", f"{PREFIX} DC strings", 537, "no"),
        ]:
            db.session.add(ActivityQuantity(
                wbs_code=wbs, item=item, total_quantity=quantity, unit=unit,
                source_document_id=layout_doc.id, revision="A",
                notes="Demonstration quantity."))

        # ---- daily records ------------------------------------------------
        QUANTITY_ACTIVITIES = [
            ("1.3.1", "Foundation piles ramming", "no", 60),
            ("1.2.2", "Drainage system works", "m", 45),
            ("1.3.2", "Mounting structure installation", "no", 6),
        ]
        cumulative = {code: 0.0 for code, _, _, _ in QUANTITY_ACTIVITIES}
        blocker_causes = ["Material", "Weather", "Design", "Equipment", "Access", "Grid/DSO"]

        for offset in range(41, -1, -1):
            day = today - timedelta(days=offset)
            if day.weekday() == 6:  # no Sunday working in the demo data
                continue
            report = DailySiteReport(
                report_date=day, report_number=f"{PREFIX}-DSR-{41 - offset + 1:04d}",
                weather=random.choice(["Clear", "Partly cloudy", "Cloudy", "Rain"]),
                weather_pm=random.choice(["Clear", "Partly cloudy", "Cloudy"]),
                temperature_min_c=round(random.uniform(9, 17), 1),
                temperature_max_c=round(random.uniform(20, 31), 1),
                shift="DAY", prepared_by=f"{PREFIX} Site Manager",
                contractor_id=contractors[0].id,
                subcontractors=", ".join(c.name for c in contractors[1:]),
                work_start_time="07:30", work_end_time="17:30",
                max_wind_ms=round(random.uniform(2, 12), 1),
                max_rain_mm_h=round(random.uniform(0, 4), 1),
                general_comments=f"{PREFIX} daily record.",
            )
            # One demonstration day exceeds the contractual wind threshold so the
            # adverse-weather banner and its evidence rule can be seen working.
            if offset == 12:
                report.max_wind_ms = 33.5
                report.adverse_weather_claimed = True
            db.session.add(report)
            db.session.flush()

            affected = random.random() < 0.22
            for code, name, unit, target in QUANTITY_ACTIVITIES:
                planned = target
                actual = max(0, round(target * random.uniform(0.55, 1.15)))
                if affected and code == "1.3.1":
                    actual = round(actual * 0.4)
                workers = random.randint(6, 14)
                db.session.add(DailyProgress(
                    daily_report_id=report.id, entry_date=day, wbs_code=code,
                    activity_name=f"{name}", work_package="Demo work package",
                    area_id=random.choice(areas).id, planned_quantity=planned,
                    actual_quantity=actual, unit=unit,
                    cumulative_before=cumulative[code], total_required_quantity=None,
                    workers=workers, hours=10,
                    comments=f"{PREFIX} progress line.",
                    activity_affected=affected and code == "1.3.1",
                    blocker_category=random.choice(blocker_causes) if (affected and code == "1.3.1") else None,
                    estimated_lost_hours=round(random.uniform(2, 6), 1) if (affected and code == "1.3.1") else 0.0,
                ))
                cumulative[code] += actual

            if affected:
                cause = random.choice(blocker_causes)
                db.session.add(Blocker(
                    blocker_number=numbering.next_blocker_number(), entry_date=day,
                    daily_report_id=report.id, wbs_code="1.3.1",
                    area_id=random.choice(areas).id, activity="Foundation piles ramming",
                    category=cause, description=f"{PREFIX} blocker: {cause.lower()} constraint",
                    estimated_lost_hours=round(random.uniform(2, 8), 1),
                    workers_affected=random.randint(4, 12),
                    status="OPEN" if random.random() < 0.4 else "CLOSED",
                    responsible_party=f"{PREFIX} EPC Contractor SpA"))
                db.session.flush()

            for contractor in contractors[1:]:
                db.session.add(WorkforceEntry(
                    daily_report_id=report.id, entry_date=day,
                    contractor_id=contractor.id, discipline=contractor.discipline,
                    area_id=random.choice(areas).id,
                    workers=random.randint(4, 16), hours=10,
                    overtime_hours=random.choice([0, 0, 0, 8, 12])))

            for equipment in ["Pile driving rig", "Excavator 20 t", "Telehandler", "Crane 40 t"]:
                working_hours = round(random.uniform(4, 9), 1)
                db.session.add(EquipmentEntry(
                    daily_report_id=report.id, entry_date=day, equipment_type=equipment,
                    contractor_id=random.choice(contractors).id,
                    area_id=random.choice(areas).id, quantity=random.randint(1, 3),
                    status="WORKING" if working_hours > 5 else "IDLE",
                    working_hours=working_hours,
                    idle_hours=round(random.uniform(0, 3), 1),
                    breakdown_hours=round(random.uniform(0, 1.5), 1),
                    reason="Demonstration record"))

            if random.random() < 0.3:
                db.session.add(SiteObservation(
                    daily_report_id=report.id, entry_date=day,
                    area_id=random.choice(areas).id,
                    observation=f"{PREFIX} observation recorded on {day:%d/%m/%Y}",
                    category=random.choice(["Progress", "Quality", "HSE", "Drainage", "Access"]),
                    severity=random.choice(["LOW", "MEDIUM", "HIGH"]),
                    action_required=f"{PREFIX} action",
                    responsible_party=f"{PREFIX} Site Manager",
                    target_date=day + timedelta(days=random.randint(2, 14)),
                    status="OPEN" if random.random() < 0.5 else "CLOSED"))

        # ---- procurement ---------------------------------------------------
        packages = [
            ("PKG-01", "PV Modules", "no", 13965, 55, True),
            ("PKG-02", "Inverters", "no", 37, 30, True),
            ("PKG-04", "Transformers", "no", 6, -5, True),
            ("PKG-08", "DC Cables", "m", 120000, 12, False),
            ("PKG-10", "Mounting Structures", "no", 341, -18, False),
        ]
        for code, name, unit, quantity, delivery_offset, fat in packages:
            package = ProcurementPackage(
                package_code=f"{PREFIX}-{code}", package_name=f"{PREFIX} {name}",
                category=name, stage=random.choice(
                    ["CONTRACTED/ORDERED", "MANUFACTURING", "SHIPPED", "DELIVERED"]),
                planned_delivery=today + timedelta(days=delivery_offset),
                forecast_delivery=today + timedelta(days=delivery_offset + 4),
                fat_required=fat, fat_status="PLANNED" if fat else "NOT REQUIRED",
                responsible_party=f"{PREFIX} Procurement",
                approved_vendors=f"{PREFIX} approved vendor list")
            db.session.add(package)
            db.session.flush()
            delivered = round(quantity * random.uniform(0.0, 0.7))
            accepted = round(delivered * random.uniform(0.85, 1.0))
            material = Material(
                package_id=package.id, item=f"{PREFIX} {name} supply", unit=unit,
                manufacturer=f"{PREFIX} Manufacturer", vendor=f"{PREFIX} Vendor",
                approved_vendor=random.random() < 0.8,
                contract_quantity=quantity, total_required=quantity,
                ordered=quantity, manufactured=round(quantity * 0.8),
                delivered=delivered, accepted=accepted,
                installed=round(accepted * random.uniform(0.0, 0.6)),
                planned_delivery=package.planned_delivery,
                forecast_delivery=package.forecast_delivery,
                fat_required=fat, fat_status=package.fat_status,
                po_reference=f"{PREFIX}-PO-{code}")
            db.session.add(material)
            db.session.flush()
            if delivered:
                db.session.add(Delivery(
                    material_id=material.id, package_id=package.id,
                    delivery_date=today - timedelta(days=random.randint(1, 30)),
                    delivery_note_reference=f"{PREFIX}-DDT-{code}", quantity=delivered,
                    unit=unit, status="ACCEPTED", accepted_quantity=accepted,
                    rejected_quantity=delivered - accepted,
                    inspection_date=today - timedelta(days=random.randint(0, 5)),
                    inspected_by=f"{PREFIX} QA/QC"))
                db.session.add(MaterialTransaction(
                    material_id=material.id, transaction_date=today - timedelta(days=20),
                    transaction_type="RECEIPT ACCEPTED", quantity=accepted,
                    reference=f"{PREFIX}-DDT-{code}"))
                db.session.add(MaterialTransaction(
                    material_id=material.id, transaction_date=today - timedelta(days=10),
                    transaction_type="ISSUE TO WORKFRONT",
                    quantity=round(accepted * 0.6), area_id=areas[0].id,
                    reference=f"{PREFIX}-ISSUE"))

        # ---- quality --------------------------------------------------------
        for reference, inspection_type, point_type, wbs in [
            (f"{PREFIX}-ITP-01", "Dimensional check", "WITNESS", "1.3.2"),
            (f"{PREFIX}-ITP-02", "Torque check", "WITNESS", "1.3.3"),
            (f"{PREFIX}-ITP-03", "Electrical test", "HOLD", "1.3.4"),
            (f"{PREFIX}-ITP-04", "Visual inspection", "REVIEW", "1.2.2"),
        ]:
            db.session.add(InspectionRequirement(
                wbs_code=wbs, work_package="Demo work package", itp_reference=reference,
                inspection_type=inspection_type, point_type=point_type,
                required_evidence=f"{PREFIX} evidence", acceptance_criterion=f"{PREFIX} criterion",
                applicable_specification=f"{PREFIX} specification"))

        for record_type, count in [("NCR", 4), ("PUNCH LIST", 9), ("INSPECTION", 7),
                                   ("TEST RECORD", 3)]:
            for index in range(count):
                raised = today - timedelta(days=random.randint(1, 40))
                closed = random.random() < 0.45
                db.session.add(QualityRecord(
                    record_number=numbering.next_quality_number(record_type),
                    record_type=record_type, record_date=raised,
                    wbs_code=random.choice(["1.2.2", "1.3.1", "1.3.2", "1.3.4"]),
                    area_id=random.choice(areas).id,
                    title=f"{PREFIX} {record_type.title()} {index + 1}",
                    description=f"{PREFIX} demonstration record.",
                    responsible_party=f"{PREFIX} EPC Contractor SpA",
                    severity=random.choice(["LOW", "MEDIUM", "HIGH"]),
                    target_closure_date=raised + timedelta(days=random.randint(3, 20)),
                    status="CLOSED" if closed else random.choice(
                        ["OPEN", "ACTION REQUIRED", "READY FOR REINSPECTION"]),
                    closure_date=raised + timedelta(days=10) if closed else None,
                    inspection_result=random.choice(["PASS", "FAIL", "PASS WITH COMMENTS"])
                    if record_type in {"INSPECTION", "TEST RECORD"} else None))
                db.session.flush()

        # ---- RFIs -----------------------------------------------------------
        for index in range(6):
            raised = today - timedelta(days=random.randint(2, 45))
            answered = random.random() < 0.5
            db.session.add(Rfi(
                rfi_number=numbering.next_rfi_number(), date_raised=raised,
                raised_by=f"{PREFIX} Site Engineer",
                area_id=random.choice(areas).id,
                wbs_code=random.choice(["1.2.2", "1.3.1", "1.3.4"]),
                discipline=random.choice(["Civil", "Electrical", "Mechanical"]),
                subject=f"{PREFIX} technical query {index + 1}",
                question=f"{PREFIX} question text.",
                responsible_party=f"{PREFIX} Designer",
                required_response_date=raised + timedelta(days=7),
                response_date=raised + timedelta(days=6) if answered else None,
                response=f"{PREFIX} response." if answered else None,
                status="ANSWERED" if answered else "OPEN",
                schedule_impact=random.random() < 0.3,
                estimated_delay_days=random.choice([None, 2, 5, 10])))
            db.session.flush()

        # ---- permits ---------------------------------------------------------
        for name, authority, status, offset in [
            ("Authorisation to construct", "Demo Province", "ISSUED", -300),
            ("Start-of-works notification", "Demo Municipality", "SUBMITTED", -20),
            ("Financial guarantee", "Demo Municipality", "IN PREPARATION", 10),
            ("Grid connection readiness", "Demo DSO", "NOT STARTED", 90),
        ]:
            db.session.add(PermitItem(
                item_name=f"{PREFIX} {name}", authority=f"{PREFIX} {authority}",
                responsibility=f"{PREFIX} Client", required_for=f"{PREFIX} milestone",
                required_by_date=today + timedelta(days=offset),
                issued_date=today + timedelta(days=offset) if status == "ISSUED" else None,
                status=status, verified=status == "ISSUED",
                document_reference=f"{PREFIX}-DOC-{abs(offset)}"))

        # ---- acceptance gates and documents ------------------------------------
        GATE_ITEMS = {
            "A": ["Modules installed", "Structures installed", "Cables installed",
                  "Earthing complete", "SCADA/DC/LV/MV terminations complete",
                  "CCTV and monitoring installed", "All work packages complete",
                  "Cold commissioning complete", "Civil reinstatement complete",
                  "Grid readiness documentation", "Works Completion Statement",
                  "Client Completion Visit", "Punch List agreed"],
            "B": ["Works Completion Certificate", "Energisation", "String-level operation",
                  "Monitoring visibility", "CCTV visibility", "DSO grid connection test",
                  "IEC 62446 tests", "Earthing tests", "Inverter tests", "Transformer tests",
                  "Switchgear tests", "VLF tests", "Cable tests",
                  "SCADA and CCTV commissioning", "Functional tests",
                  "Commissioning documentation"],
            "C": ["Works Completion Certificate", "Commissioning Certificate",
                  "Project documentation", "Performance test", "Punch List closure",
                  "As-built documents", "Manuals", "Warranty Bond", "Spare parts",
                  "O&M prerequisites", "PAC certificate"],
            "D": ["Defects Notification Period", "Outstanding defects",
                  "Final performance requirements", "Final Punch List",
                  "Final Acceptance prerequisites", "Final Acceptance Certificate"],
        }
        STATUS_MIX = {
            "A": ["ACCEPTED", "ACCEPTED", "ACCEPTED", "READY", "IN PROGRESS", "NOT STARTED"],
            "B": ["ACCEPTED", "IN PROGRESS", "NOT STARTED", "NOT STARTED"],
            "C": ["NOT STARTED", "NOT STARTED", "IN PROGRESS"],
            "D": ["NOT STARTED"],
        }
        for gate in AcceptanceGate.query.order_by(AcceptanceGate.sequence).all():
            for index, name in enumerate(GATE_ITEMS.get(gate.gate_code, []), start=1):
                db.session.add(AcceptanceGateItem(
                    gate_id=gate.id, item_code=f"{gate.gate_code}-{index:02d}",
                    item_name=f"{PREFIX} {name}", category="Demonstration",
                    responsible_party=f"{PREFIX} EPC Contractor SpA",
                    target_date=today + timedelta(days=60 + index * 3),
                    status=random.choice(STATUS_MIX[gate.gate_code]), sequence=index))
            for index, title in enumerate(["Test report", "As-built drawing", "Certificate"],
                                          start=1):
                db.session.add(DocumentRegisterItem(
                    document_number=f"{PREFIX}-{gate.gate_code}-{index:02d}",
                    title=f"{PREFIX} {title} for gate {gate.gate_code}",
                    category=random.choice(["Test", "As-Built", "Acceptance"]),
                    status=random.choice(["NOT STARTED", "SUBMITTED", "ACCEPTED"]),
                    required_date=today + timedelta(days=60), gate_code=gate.gate_code,
                    mandatory=True))

        DEMO_PAYMENTS = [
            (1, "PM-01", "Contract signature advance payment", 15.0, "PAID"),
            (2, "PM-02", "Completion of site preparation works", 10.0, "CERTIFIED"),
            (3, "PM-03", "Delivery of substructure", 10.0, "ACHIEVED"),
            (4, "PM-04", "Delivery of modules and inverters", 30.0, "IN PROGRESS"),
            (5, "PM-05", "Completion of substructure and module assembly", 10.0, "NOT STARTED"),
            (6, "PM-06", "Delivery of transformer stations", 5.0, "NOT STARTED"),
            (7, "PM-07", "Completion of the whole electrical works", 10.0, "NOT STARTED"),
            (8, "PM-08", "Pre provisional acceptance", 5.0, "NOT STARTED"),
            (9, "PM-09", "Provisional acceptance and punch list closure", 5.0, "NOT STARTED"),
        ]
        for sequence, code, description, percentage, status in DEMO_PAYMENTS:
            offset = -90 + sequence * 30
            db.session.add(PaymentMilestone(
                sequence=sequence, milestone_code=f"{PREFIX}-{code}",
                description=f"{PREFIX} {description}", percentage=percentage,
                planned_date=today + timedelta(days=offset),
                forecast_date=today + timedelta(days=offset + 10),
                achieved_date=(today + timedelta(days=offset + 12)
                               if status in {"ACHIEVED", "CERTIFIED", "PAID"} else None),
                certified_date=(today + timedelta(days=offset + 20)
                                if status in {"CERTIFIED", "PAID"} else None),
                paid_date=(today + timedelta(days=offset + 40) if status == "PAID" else None),
                status=status, gate_code="C" if sequence == 9 else None,
                comments="Demonstration milestone."))

        db.session.commit()

        print("Demonstration data created.")
        print(f"  Database          : {DEMO_DB}")
        print(f"  Daily reports     : {DailySiteReport.query.count()}")
        print(f"  Progress lines    : {DailyProgress.query.count()}")
        print(f"  Activities        : {WbsActivity.query.count()}")
        print(f"  Blockers          : {Blocker.query.count()}")
        print(f"  Quality records   : {QualityRecord.query.count()}")
        print(f"  Gate items        : {AcceptanceGateItem.query.count()}")
        print(f"  Payment milestones: {PaymentMilestone.query.count()}")
        return app


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--reset", action="store_true",
                        help="delete the demo database before rebuilding it")
    parser.add_argument("--run", action="store_true",
                        help="start the application against the demo database afterwards")
    parser.add_argument("--port", type=int, default=5001,
                        help="port to use with --run (default 5001, to avoid clashing "
                             "with the live instance)")
    args = parser.parse_args(argv)

    DEMO_DB.parent.mkdir(parents=True, exist_ok=True)
    if args.reset and DEMO_DB.exists():
        DEMO_DB.unlink()
        print(f"Deleted {DEMO_DB}")

    print("=" * 72)
    print("  DEMONSTRATION DATA")
    print("  Writing to a separate database. The live Bassignana database at")
    print("  data/bassignana.db is never touched by this script.")
    print("=" * 72)

    app = seed()

    if args.run:
        import run as runner
        runner.banner("0.0.0.0", args.port, app)
        print("  *** THIS INSTANCE IS SHOWING DEMONSTRATION DATA ***")
        app.run(host="0.0.0.0", port=args.port, threaded=True)
    else:
        print()
        print("To view it, start the application against the demo database:")
        print("  Windows PowerShell:")
        print(f'    $env:BASSIGNANA_DATABASE_URI = "{DEMO_URI}"')
        print("    python run.py")
        print("  Linux / macOS:")
        print(f'    BASSIGNANA_DATABASE_URI="{DEMO_URI}" python run.py')
        print()
        print("Or simply:  python seed_demo.py --run")
    return 0


if __name__ == "__main__":
    sys.exit(main())
