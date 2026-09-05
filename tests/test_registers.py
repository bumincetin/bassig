"""Blockers, quality, procurement, stock and acceptance-gate readiness."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from app import constants as C
from app.models import (
    AcceptanceGate,
    AcceptanceGateItem,
    Blocker,
    Delivery,
    DocumentRegisterItem,
    Material,
    MaterialTransaction,
    ProcurementPackage,
    QualityRecord,
    Rfi,
)
from app.services import numbering, procurement_service, registers
from app.services.status_rules import (
    gate_readiness,
    procurement_status,
    quality_status,
    rfi_status,
    stock_status,
)


# ==========================================================================
# Blockers
# ==========================================================================
class TestBlockers:
    def _blocker(self, db, category, estimated, actual=None, workers=0, day=None):
        row = Blocker(
            blocker_number=numbering.next_blocker_number(),
            entry_date=day or date(2026, 9, 4),
            category=category, estimated_lost_hours=estimated,
            actual_lost_hours=actual, workers_affected=workers, status="OPEN",
        )
        db.session.add(row)
        db.session.commit()
        return row

    def test_actual_hours_take_precedence_over_the_estimate(self, app, db):
        row = self._blocker(db, "Material", estimated=8.0, actual=5.5)
        assert row.effective_lost_hours == pytest.approx(5.5)

    def test_estimate_is_used_when_no_actual_is_recorded(self, app, db):
        row = self._blocker(db, "Material", estimated=8.0)
        assert row.effective_lost_hours == pytest.approx(8.0)

    def test_zero_actual_hours_is_respected_not_treated_as_missing(self, app, db):
        row = self._blocker(db, "Weather", estimated=8.0, actual=0.0)
        assert row.effective_lost_hours == pytest.approx(0.0)

    def test_lost_man_hours(self, app, db):
        row = self._blocker(db, "Design", estimated=4.0, workers=12)
        assert row.lost_man_hours == pytest.approx(48.0)

    def test_summary_totals_by_category(self, app, db):
        self._blocker(db, "Material", 8.0, workers=10)
        self._blocker(db, "Material", 4.0, workers=5)
        self._blocker(db, "Weather", 6.0, workers=20)
        summary = registers.blocker_summary()
        assert summary["total"] == 3
        assert summary["lost_hours"] == pytest.approx(18.0)
        assert summary["lost_man_hours"] == pytest.approx(220.0)
        by_category = {c["category"]: c for c in summary["by_category"]}
        assert by_category["Material"]["incidents"] == 2
        assert by_category["Material"]["lost_hours"] == pytest.approx(12.0)

    def test_top_cause_is_the_largest_by_lost_hours(self, app, db):
        self._blocker(db, "Material", 2.0)
        self._blocker(db, "Grid/DSO", 20.0)
        assert registers.blocker_summary()["top_cause"]["category"] == "Grid/DSO"

    def test_recurring_causes_need_three_incidents(self, app, db):
        for _ in range(3):
            self._blocker(db, "Access", 1.0)
        self._blocker(db, "HSE", 1.0)
        recurring = {c["category"] for c in registers.blocker_summary()["recurring"]}
        assert recurring == {"Access"}

    def test_blocker_numbers_increment(self, app, db):
        first = self._blocker(db, "Material", 1.0)
        second = self._blocker(db, "Material", 1.0)
        assert first.blocker_number == "BAS-BLK-0001"
        assert second.blocker_number == "BAS-BLK-0002"


# ==========================================================================
# Quality
# ==========================================================================
class TestQualityRegister:
    def _record(self, db, record_type, status="OPEN", target=None):
        row = QualityRecord(
            record_number=numbering.next_quality_number(record_type),
            record_type=record_type, record_date=date(2026, 9, 1),
            title=f"{record_type} test record", status=status,
            target_closure_date=target,
        )
        db.session.add(row)
        db.session.commit()
        return row

    def test_ncr_numbering(self, app, db):
        assert self._record(db, "NCR").record_number == "BAS-NCR-0001"

    def test_punch_numbering_is_independent_of_ncr(self, app, db):
        self._record(db, "NCR")
        assert self._record(db, "PUNCH LIST").record_number == "BAS-PUN-0001"

    def test_inspection_numbering(self, app, db):
        assert self._record(db, "INSPECTION").record_number == "BAS-INS-0001"

    def test_numbering_continues_from_the_highest_existing(self, app, db):
        self._record(db, "NCR")
        self._record(db, "NCR")
        assert numbering.next_quality_number("NCR") == "BAS-NCR-0003"

    def test_open_record_past_its_target_is_overdue(self, app, db):
        row = self._record(db, "NCR", target=date(2026, 8, 1))
        assert quality_status(row, date(2026, 9, 4)) == "OVERDUE"

    def test_closed_record_is_never_overdue(self, app, db):
        row = self._record(db, "NCR", status="CLOSED", target=date(2026, 8, 1))
        assert quality_status(row, date(2026, 9, 4)) == "CLOSED"

    def test_accepted_record_is_never_overdue(self, app, db):
        row = self._record(db, "PUNCH LIST", status="ACCEPTED", target=date(2026, 8, 1))
        assert quality_status(row, date(2026, 9, 4)) == "ACCEPTED"

    def test_record_without_a_target_is_not_overdue(self, app, db):
        row = self._record(db, "NCR")
        assert quality_status(row, date(2026, 9, 4)) == "OPEN"

    def test_overdue_detection_lists_both_registers_separately(self, app, db):
        self._record(db, "NCR", target=date(2026, 8, 1))
        self._record(db, "PUNCH LIST", target=date(2026, 8, 1))
        assert len(registers.overdue_quality("NCR", date(2026, 9, 4))) == 1
        assert len(registers.overdue_quality("PUNCH LIST", date(2026, 9, 4))) == 1

    def test_summary_keeps_ncr_and_punch_apart(self, app, db):
        self._record(db, "NCR", target=date(2026, 8, 1))
        self._record(db, "PUNCH LIST")
        self._record(db, "PUNCH LIST")
        summary = registers.quality_summary(date(2026, 9, 4))
        assert summary["open_ncr"] == 1
        assert summary["open_punch"] == 2
        assert summary["overdue_ncr"] == 1
        assert summary["overdue_punch"] == 0


class TestRfiRegister:
    def _rfi(self, db, status="OPEN", required=None, responded=None):
        row = Rfi(rfi_number=numbering.next_rfi_number(), date_raised=date(2026, 9, 1),
                  subject="Cable trench depth", status=status,
                  required_response_date=required, response_date=responded)
        db.session.add(row)
        db.session.commit()
        return row

    def test_rfi_numbering(self, app, db):
        assert self._rfi(db).rfi_number == "BAS-RFI-0001"

    def test_open_rfi_past_its_required_date_is_overdue(self, app, db):
        row = self._rfi(db, required=date(2026, 8, 20))
        assert rfi_status(row, date(2026, 9, 4)) == "OVERDUE"

    def test_answered_rfi_is_not_overdue(self, app, db):
        row = self._rfi(db, status="ANSWERED", required=date(2026, 8, 20))
        assert rfi_status(row, date(2026, 9, 4)) == "ANSWERED"

    def test_summary_counts(self, app, db):
        self._rfi(db, required=date(2026, 8, 20))
        self._rfi(db, status="ANSWERED")
        self._rfi(db, status="CLOSED")
        summary = registers.rfi_summary(date(2026, 9, 4))
        assert summary["total"] == 3
        assert summary["overdue"] == 1
        assert summary["answered"] == 1
        assert summary["closed"] == 1


# ==========================================================================
# Procurement and stock
# ==========================================================================
class TestProcurement:
    @pytest.fixture()
    def package(self, db):
        row = ProcurementPackage(package_code="PKG-01", package_name="PV Modules",
                                 stage="CONTRACTED/ORDERED")
        db.session.add(row)
        db.session.commit()
        return row

    def _material(self, db, package, **kwargs):
        defaults = dict(item="PV modules 585 Wp", unit="no", total_required=13965.0)
        defaults.update(kwargs)
        row = Material(package_id=package.id, **defaults)
        db.session.add(row)
        db.session.commit()
        return row

    def test_late_when_the_forecast_delivery_has_passed(self, app, db, package):
        material = self._material(db, package, forecast_delivery=date(2026, 8, 1))
        assert procurement_status(material, date(2026, 9, 4)) == "LATE"

    def test_at_risk_inside_the_configured_window(self, app, db, package):
        material = self._material(db, package, forecast_delivery=date(2026, 9, 10))
        assert procurement_status(material, date(2026, 9, 4)) == "AT RISK"

    def test_on_time_outside_the_window(self, app, db, package):
        material = self._material(db, package, forecast_delivery=date(2026, 12, 1))
        assert procurement_status(material, date(2026, 9, 4)) == "ON TIME"

    def test_delivered_is_not_accepted(self, app, db, package):
        material = self._material(db, package, delivered=13965.0, accepted=0.0)
        assert procurement_status(material, date(2026, 9, 4)) == "DELIVERED"

    def test_accepted_is_not_installed(self, app, db, package):
        material = self._material(db, package, delivered=13965.0, accepted=13965.0,
                                  installed=0.0)
        assert procurement_status(material, date(2026, 9, 4)) == "ACCEPTED"

    def test_installed_is_reported_only_when_recorded(self, app, db, package):
        material = self._material(db, package, delivered=13965.0, accepted=13965.0,
                                  installed=13965.0)
        assert procurement_status(material, date(2026, 9, 4)) == "INSTALLED"

    def test_delivery_records_drive_the_material_totals(self, app, db, package):
        material = self._material(db, package)
        delivery = Delivery(material_id=material.id, package_id=package.id,
                            delivery_date=date(2026, 9, 1), quantity=5000.0,
                            accepted_quantity=4800.0, rejected_quantity=200.0,
                            status="PARTIALLY ACCEPTED")
        db.session.add(delivery)
        db.session.flush()
        procurement_service.apply_delivery_to_material(delivery)
        db.session.commit()
        assert material.delivered == pytest.approx(5000.0)
        assert material.accepted == pytest.approx(4800.0)
        # Acceptance never implies installation.
        assert material.installed == pytest.approx(0.0)

    def test_warnings_flag_unapproved_vendors(self, app, db, package):
        self._material(db, package, vendor="Unlisted Vendor Srl", approved_vendor=False)
        warnings = procurement_service.procurement_warnings(date(2026, 9, 4))
        assert len(warnings["unapproved_vendors"]) == 1

    def test_stage_distribution_covers_every_stage(self, app, db, package):
        stages = procurement_service.stage_distribution()
        assert [s["stage"] for s in stages] == C.PROCUREMENT_STAGES
        contracted = next(s for s in stages if s["stage"] == "CONTRACTED/ORDERED")
        assert contracted["count"] == 1


class TestStock:
    @pytest.fixture()
    def material(self, db):
        package = ProcurementPackage(package_code="PKG-08", package_name="DC Cables")
        db.session.add(package)
        db.session.flush()
        row = Material(package_id=package.id, item="DC cable 1x4 mm2", unit="m",
                       total_required=100000.0)
        db.session.add(row)
        db.session.commit()
        return row

    def _txn(self, db, material, txn_type, quantity):
        db.session.add(MaterialTransaction(
            material_id=material.id, transaction_date=date(2026, 9, 1),
            transaction_type=txn_type, quantity=quantity))
        db.session.commit()

    def test_available_equals_receipts_plus_adjustments_minus_issues(self, app, db, material):
        self._txn(db, material, "RECEIPT ACCEPTED", 40000)
        self._txn(db, material, "ADJUSTMENT", -500)
        self._txn(db, material, "ISSUE TO WORKFRONT", 15000)
        assert procurement_service.stock_for(material) == pytest.approx(24500.0)

    def test_returns_add_back_to_stock(self, app, db, material):
        self._txn(db, material, "RECEIPT ACCEPTED", 1000)
        self._txn(db, material, "ISSUE TO WORKFRONT", 400)
        self._txn(db, material, "RETURN TO STORE", 100)
        assert procurement_service.stock_for(material) == pytest.approx(700.0)

    def test_no_movements_gives_zero_stock(self, app, db, material):
        assert procurement_service.stock_for(material) == pytest.approx(0.0)

    def test_stock_status_shortage_when_nothing_available(self, app):
        assert stock_status(0, 5000) == C.STOCK_SHORTAGE

    def test_stock_status_low_below_the_threshold(self, app):
        assert stock_status(500, 5000) == C.STOCK_LOW

    def test_stock_status_ok_above_the_threshold(self, app):
        assert stock_status(4000, 5000) == C.STOCK_OK

    def test_no_remaining_requirement_is_ok(self, app):
        assert stock_status(0, 0) == C.STOCK_OK

    def test_material_view_reports_remaining_requirement(self, app, db, material):
        material.installed = 30000.0
        db.session.commit()
        view = procurement_service.material_view(material, date(2026, 9, 4))
        assert view["remaining_requirement"] == pytest.approx(70000.0)


# ==========================================================================
# Acceptance gates
# ==========================================================================
class TestAcceptanceGates:
    def _item(self, db, gate, name, status="NOT STARTED"):
        row = AcceptanceGateItem(gate_id=gate.id, item_name=name, status=status,
                                 sequence=len(gate.items) + 1)
        db.session.add(row)
        db.session.commit()
        return row

    def test_four_gates_are_created_on_first_run(self, app):
        codes = {g.gate_code for g in AcceptanceGate.query.all()}
        assert codes == {"A", "B", "C", "D"}

    def test_gates_start_with_no_items(self, app, gate_a):
        assert gate_a.items == []

    def test_readiness_is_none_without_items(self, app, gate_a):
        percent, satisfied, considered = gate_readiness(gate_a.items)
        assert percent is None and satisfied == 0 and considered == 0

    def test_only_accepted_items_count_as_satisfied(self, app, db, gate_a):
        self._item(db, gate_a, "Modules installed", "ACCEPTED")
        self._item(db, gate_a, "Cables installed", "READY")
        self._item(db, gate_a, "Earthing complete", "SUBMITTED")
        self._item(db, gate_a, "Cold commissioning complete", "IN PROGRESS")
        percent, satisfied, considered = gate_readiness(gate_a.items)
        assert satisfied == 1
        assert considered == 4
        assert percent == pytest.approx(25.0)

    def test_not_applicable_items_leave_the_denominator(self, app, db, gate_a):
        self._item(db, gate_a, "Modules installed", "ACCEPTED")
        self._item(db, gate_a, "Not in scope", "NOT APPLICABLE")
        percent, satisfied, considered = gate_readiness(gate_a.items)
        assert considered == 1
        assert percent == pytest.approx(100.0)

    def test_full_readiness_does_not_accept_the_gate(self, app, db, gate_a):
        self._item(db, gate_a, "Everything", "ACCEPTED")
        view = next(v for v in registers.gate_views() if v["gate"].gate_code == "A")
        assert view["readiness_pct"] == pytest.approx(100.0)
        assert view["derived_state"] == "READY"
        # The recorded contractual status is untouched by the calculation.
        assert view["gate"].status == "NOT STARTED"

    def test_rejected_items_are_surfaced(self, app, db, gate_a):
        self._item(db, gate_a, "Reinstatement", "REJECTED")
        view = next(v for v in registers.gate_views() if v["gate"].gate_code == "A")
        assert len(view["rejected_items"]) == 1

    def test_overall_readiness_weights_by_item_count(self, app, db):
        gate_a = AcceptanceGate.query.filter_by(gate_code="A").first()
        gate_b = AcceptanceGate.query.filter_by(gate_code="B").first()
        self._item(db, gate_a, "A1", "ACCEPTED")
        self._item(db, gate_a, "A2", "ACCEPTED")
        self._item(db, gate_a, "A3", "ACCEPTED")
        self._item(db, gate_b, "B1", "NOT STARTED")
        overall = registers.overall_acceptance_readiness()
        assert overall["satisfied"] == 3
        assert overall["considered"] == 4
        assert overall["percent"] == pytest.approx(75.0)

    def test_missing_mandatory_documents_are_reported_per_gate(self, app, db, gate_a):
        db.session.add(DocumentRegisterItem(title="Works Completion Statement",
                                            gate_code="A", mandatory=True,
                                            status="NOT STARTED"))
        db.session.add(DocumentRegisterItem(title="As-built layout", gate_code="A",
                                            mandatory=True, status="ACCEPTED"))
        db.session.commit()
        summary = registers.document_summary("A")
        assert summary["mandatory"] == 2
        assert summary["missing_count"] == 1
        assert summary["completeness_pct"] == pytest.approx(50.0)
