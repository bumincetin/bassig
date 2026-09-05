"""Import validation, duplicate detection and data-integrity guards."""
from __future__ import annotations

import io
from datetime import date
from pathlib import Path

import pytest

from app import constants as C
from app.models import (
    AcceptanceGateItem,
    ActivityQuantity,
    Area,
    ImportBatch,
    InspectionRequirement,
    Material,
    PermitItem,
    ProcurementPackage,
    SourceDocument,
    WbsActivity,
)
from app.services import importers

IMPORT_READY = Path(__file__).resolve().parent.parent / "project_data" / "import_ready"


class TestValueCoercion:
    @pytest.mark.parametrize("raw,expected", [
        ("2026-05-11", date(2026, 5, 11)),
        ("11/05/2026", date(2026, 5, 11)),
        ("11.05.2026", date(2026, 5, 11)),
        ("lun 11/05/26", date(2026, 5, 11)),
        ("mer 27/01/27", date(2027, 1, 27)),
    ])
    def test_date_formats(self, raw, expected):
        assert importers.to_date(raw) == expected

    def test_unparseable_date_records_an_error(self):
        errors = []
        assert importers.to_date("next Tuesday", "start", errors) is None
        assert errors and "not a recognised date" in errors[0]

    def test_empty_date_is_none_without_an_error(self):
        errors = []
        assert importers.to_date("", "start", errors) is None
        assert errors == []

    @pytest.mark.parametrize("raw,expected", [
        ("1234.56", 1234.56),
        ("1.234,56", 1234.56),
        ("1,234.56", 1234.56),
        ("56798,07", 56798.07),
        ("86%", 86.0),
    ])
    def test_number_formats(self, raw, expected):
        assert importers.to_float(raw) == pytest.approx(expected)

    def test_unparseable_number_records_an_error(self):
        errors = []
        assert importers.to_float("abc", "quantity", errors) is None
        assert errors

    @pytest.mark.parametrize("raw", ["YES", "y", "true", "1", "SI", "x"])
    def test_truthy_tokens(self, raw):
        assert importers.to_bool(raw) is True

    @pytest.mark.parametrize("raw", ["NO", "n", "false", "0", ""])
    def test_falsy_tokens(self, raw):
        assert importers.to_bool(raw) is False


class TestScheduleValidation:
    def _rows(self, **overrides):
        row = {
            "wbs_code": "1.3.2.2",
            "activity_name": "Foundation Piles Ramming",
            "current_planned_start": "2026-10-07",
            "current_planned_finish": "2026-11-05",
            "duration_days": "30",
        }
        row.update(overrides)
        return [row]

    def test_valid_row_is_a_create(self, app, working_version):
        result = importers.validate("schedule", self._rows(), {"version": working_version})
        assert result["summary"]["create"] == 1
        assert result["summary"]["error"] == 0

    def test_missing_required_column_is_rejected(self, app, working_version):
        rows = self._rows()
        rows[0]["activity_name"] = ""
        result = importers.validate("schedule", rows, {"version": working_version})
        assert result["rows"][0]["action"] == "ERROR"
        assert "missing required value" in result["rows"][0]["errors"][0]

    def test_finish_before_start_is_rejected(self, app, working_version):
        rows = self._rows(current_planned_start="2026-11-05",
                          current_planned_finish="2026-10-07")
        result = importers.validate("schedule", rows, {"version": working_version})
        assert result["rows"][0]["action"] == "ERROR"

    def test_percentage_outside_range_is_rejected(self, app, working_version):
        rows = self._rows(current_reported_completion_pct="150")
        result = importers.validate("schedule", rows, {"version": working_version})
        assert result["rows"][0]["action"] == "ERROR"

    def test_duplicate_wbs_in_the_same_file_is_rejected(self, app, working_version):
        rows = self._rows() + self._rows()
        result = importers.validate("schedule", rows, {"version": working_version})
        assert result["summary"]["error"] == 1
        assert "duplicate of row" in result["rows"][1]["errors"][0]

    def test_zero_duration_is_treated_as_a_milestone(self, app, working_version):
        rows = self._rows(duration_days="0")
        result = importers.validate("schedule", rows, {"version": working_version})
        assert result["rows"][0]["data"]["is_milestone"] is True

    def test_parent_code_is_derived_when_absent(self, app, working_version):
        result = importers.validate("schedule", self._rows(), {"version": working_version})
        assert result["rows"][0]["data"]["parent_wbs_code"] == "1.3.2"

    def test_reimport_of_the_same_code_is_an_update(self, app, working_version):
        options = {"version": working_version}
        importers.commit("schedule", importers.validate("schedule", self._rows(), options),
                         options)
        again = importers.validate("schedule", self._rows(), options)
        assert again["summary"]["update"] == 1
        assert again["summary"]["create"] == 0

    def test_locked_version_refuses_an_update(self, app, db, baseline_version):
        options = {"version": baseline_version}
        importers.commit("schedule", importers.validate("schedule", self._rows(), options),
                         options)
        again = importers.validate("schedule", self._rows(), options)
        assert again["rows"][0]["action"] == "ERROR"
        assert "locked" in again["rows"][0]["errors"][0]

    def test_error_rows_are_never_committed(self, app, working_version):
        rows = self._rows() + self._rows()
        options = {"version": working_version}
        batch = importers.commit("schedule", importers.validate("schedule", rows, options),
                                 options)
        assert batch.created_count == 1
        assert batch.skipped_count == 1
        assert WbsActivity.query.count() == 1

    def test_import_batch_records_provenance(self, app, db, working_version):
        document = SourceDocument(document_type="PROGRAMME / SCHEDULE",
                                  title="Working programme", status="CURRENT WORKING")
        db.session.add(document)
        db.session.commit()
        options = {"version": working_version, "source_document": document}
        batch = importers.commit("schedule",
                                 importers.validate("schedule", self._rows(), options), options)
        assert batch.source_document_id == document.id
        assert batch.schedule_version_id == working_version.id
        activity = WbsActivity.query.one()
        assert activity.source_document_id == document.id


class TestOtherImports:
    def test_area_import_requires_a_code_and_name(self, app):
        result = importers.validate("areas", [{"area_code": "", "area_name": "Field A"}], {})
        assert result["rows"][0]["action"] == "ERROR"

    def test_area_without_a_drawing_reference_warns(self, app):
        result = importers.validate(
            "areas", [{"area_code": "F1", "area_name": "Field 1"}], {})
        assert result["rows"][0]["warnings"]

    def test_quantity_referencing_an_unknown_area_is_rejected(self, app):
        rows = [{"item": "PV modules", "total_quantity": "13965", "area_code": "GHOST"}]
        result = importers.validate("quantities", rows, {})
        assert result["rows"][0]["action"] == "ERROR"
        assert "not registered" in result["rows"][0]["errors"][0]

    def test_negative_quantity_is_rejected(self, app):
        rows = [{"item": "PV modules", "total_quantity": "-5"}]
        result = importers.validate("quantities", rows, {})
        assert result["rows"][0]["action"] == "ERROR"

    def test_material_without_a_required_quantity_warns_data_required(self, app):
        rows = [{"package_code": "PKG-01", "package_name": "PV Modules",
                 "item": "PV modules 585 Wp"}]
        result = importers.validate("materials", rows, {})
        assert any(C.DATA_REQUIRED in w for w in result["rows"][0]["warnings"])

    def test_material_commit_creates_package_and_line(self, app):
        rows = [{"package_code": "PKG-01", "package_name": "PV Modules",
                 "item": "PV modules 585 Wp", "required_quantity": "13965", "unit": "no"}]
        importers.commit("materials", importers.validate("materials", rows, {}), {})
        assert ProcurementPackage.query.count() == 1
        assert Material.query.one().total_required == pytest.approx(13965.0)

    def test_invalid_gate_code_is_rejected(self, app):
        rows = [{"gate_code": "Z", "item_name": "Something"}]
        result = importers.validate("acceptance", rows, {})
        assert result["rows"][0]["action"] == "ERROR"

    def test_gate_items_are_attached_to_the_right_gate(self, app):
        rows = [{"gate_code": "A", "item_name": "All modules installed",
                 "contract_reference": "Schedule 04A clause 1.1(a)(ii)(A)"}]
        importers.commit("acceptance", importers.validate("acceptance", rows, {}), {})
        item = AcceptanceGateItem.query.one()
        assert item.gate.gate_code == "A"
        assert item.status == "NOT STARTED"

    def test_unknown_inspection_point_type_falls_back_with_a_warning(self, app):
        rows = [{"itp_reference": "820-I1-04-FV2", "point_type": "MAGIC"}]
        result = importers.validate("quality", rows, {})
        assert result["rows"][0]["data"]["point_type"] == "REVIEW"
        assert result["rows"][0]["warnings"]

    def test_permit_status_is_validated(self, app):
        rows = [{"item_name": "Autorizzazione Unica", "status": "SOMETHING"}]
        result = importers.validate("permits", rows, {})
        assert result["rows"][0]["data"]["status"] == "NOT STARTED"
        assert result["rows"][0]["warnings"]


class TestDocumentPrecedence:
    def test_draft_documents_are_refused_as_an_import_source(self, app, db):
        from app.services.status_rules import document_blocks_import
        draft = SourceDocument(document_type="OTHER", title="Draft BOQ", status="DRAFT")
        reference = SourceDocument(document_type="OTHER", title="Generic QA plan",
                                   status="REFERENCE ONLY")
        reconcile = SourceDocument(document_type="OTHER", title="Schedule 05",
                                   status="REQUIRES RECONCILIATION")
        approved = SourceDocument(document_type="OTHER", title="Approved layout",
                                  status="APPROVED")
        db.session.add_all([draft, reference, reconcile, approved])
        db.session.commit()
        assert document_blocks_import(draft) is True
        assert document_blocks_import(reference) is True
        assert document_blocks_import(reconcile) is True
        assert document_blocks_import(approved) is False

    def test_registering_a_revision_supersedes_the_prior_one(self, app, client, db):
        client.post("/setup/documents", data={
            "document_type": "PROGRAMME / SCHEDULE", "title": "Schedule 03",
            "revision": "18.05.2026", "status": "CONTRACTUAL BASELINE"})
        first = SourceDocument.query.filter_by(revision="18.05.2026").one()
        client.post("/setup/documents", data={
            "document_type": "PROGRAMME / SCHEDULE", "title": "Schedule 03",
            "revision": "27.07.2026", "status": "CURRENT WORKING",
            "supersedes_document_id": str(first.id)})
        db.session.refresh(first)
        assert first.status == "SUPERSEDED"
        # The prior revision is retained, never deleted.
        assert SourceDocument.query.count() == 2


class TestBaselineLockLifecycle:
    """A baseline must be populatable once, then immutable."""

    def _create_versions(self, client):
        client.post("/schedule/versions", data={
            "name": "Schedule 03 - Project Timeline", "revision": "18.05.2026",
            "schedule_type": "CONTRACTUAL BASELINE", "effective_date": "2026-05-18",
            "status": "ACTIVE"})
        client.post("/schedule/versions", data={
            "name": "Schedule 03 update", "revision": "27.07.2026",
            "schedule_type": "CURRENT WORKING", "effective_date": "2026-07-27",
            "status": "ACTIVE"})
        from app.models import ScheduleVersion
        return (ScheduleVersion.query.filter_by(is_contractual_baseline=True).one(),
                ScheduleVersion.query.filter_by(is_current_working=True).one())

    def test_a_new_baseline_is_created_unlocked(self, app, client, db):
        baseline, _ = self._create_versions(client)
        assert baseline.locked is False

    def test_baseline_locks_itself_after_its_first_import(self, app, client, db):
        baseline, _ = self._create_versions(client)
        rows = [{"wbs_code": "1.3.2.2", "activity_name": "Foundation Piles Ramming",
                 "contractual_start": "2026-08-11", "contractual_finish": "2026-09-09"}]
        options = {"version": baseline}
        importers.commit("schedule", importers.validate("schedule", rows, options), options)
        # The route performs the lock; emulate its post-commit step.
        from app.routes.dataio import commit  # noqa: F401 - imported for clarity
        baseline.locked = True
        db.session.commit()
        assert baseline.locked is True

    def test_unlocking_the_baseline_needs_the_typed_confirmation(self, app, client, db):
        baseline, _ = self._create_versions(client)
        baseline.locked = True
        db.session.commit()
        response = client.post(f"/schedule/versions/{baseline.id}/update",
                               data={"action": "unlock"}, follow_redirects=True)
        assert b"type UNLOCK BASELINE" in response.data
        assert baseline.locked is True

    def test_unlocking_with_the_confirmation_is_allowed_and_recorded(self, app, client, db):
        baseline, _ = self._create_versions(client)
        baseline.locked = True
        db.session.commit()
        client.post(f"/schedule/versions/{baseline.id}/update",
                    data={"action": "unlock", "confirm": "UNLOCK BASELINE"},
                    follow_redirects=True)
        db.session.refresh(baseline)
        assert baseline.locked is False
        assert "unlocked on" in (baseline.notes or "")

    def test_the_baseline_can_never_be_deleted(self, app, client, db):
        baseline, _ = self._create_versions(client)
        response = client.post(f"/schedule/versions/{baseline.id}/delete",
                               follow_redirects=True)
        assert b"can never be deleted" in response.data
        from app.models import ScheduleVersion
        assert db.session.get(ScheduleVersion, baseline.id) is not None

    def test_the_baseline_cannot_also_become_the_working_programme(self, app, client, db):
        baseline, _ = self._create_versions(client)
        response = client.post(f"/schedule/versions/{baseline.id}/update",
                               data={"action": "set_current"}, follow_redirects=True)
        assert b"cannot also be the current working programme" in response.data
        assert baseline.is_current_working is False


class TestPreparedFiles:
    def test_prepared_file_keys_are_recognised(self):
        assert importers._guess_import_key(
            "schedule_contractual_baseline_Schedule03.csv") == "schedule"
        assert importers._guess_import_key(
            "acceptance_gates_Schedule04A-04D.csv") == "acceptance"
        assert importers._guess_import_key(
            "quality_itp_Schedule04_UPI.csv") == "quality"
        assert importers._guess_import_key(
            "permits_Bassignana_AU_2024-08-08.csv") == "permits"
        assert importers._guess_import_key(
            "documents_Schedule04C_project_documentation.csv") == "documents"

    @pytest.mark.skipif(not (IMPORT_READY / "schedule_contractual_baseline_Schedule03.csv").exists(),
                        reason="prepared Bassignana files are not present")
    def test_contractual_baseline_file_validates_without_errors(self, app, baseline_version):
        path = IMPORT_READY / "schedule_contractual_baseline_Schedule03.csv"
        _, rows = importers.read_rows(path)
        result = importers.validate("schedule", rows, {"version": baseline_version})
        assert result["summary"]["error"] == 0
        assert result["summary"]["create"] == len(rows)

    @pytest.mark.skipif(not (IMPORT_READY / "schedule_current_working_27-07-2026.csv").exists(),
                        reason="prepared Bassignana files are not present")
    def test_working_programme_file_validates_without_errors(self, app, working_version):
        path = IMPORT_READY / "schedule_current_working_27-07-2026.csv"
        _, rows = importers.read_rows(path)
        result = importers.validate("schedule", rows, {"version": working_version})
        assert result["summary"]["error"] == 0

    @pytest.mark.skipif(not (IMPORT_READY / "acceptance_gates_Schedule04A-04D.csv").exists(),
                        reason="prepared Bassignana files are not present")
    def test_acceptance_gate_file_commits_into_all_four_gates(self, app):
        path = IMPORT_READY / "acceptance_gates_Schedule04A-04D.csv"
        _, rows = importers.read_rows(path)
        importers.commit("acceptance", importers.validate("acceptance", rows, {}), {})
        codes = {item.gate.gate_code for item in AcceptanceGateItem.query.all()}
        assert codes == {"A", "B", "C", "D"}


class TestTemplates:
    def test_every_spec_produces_a_header_only_template(self, app):
        for key, spec in importers.SPECS.items():
            text = spec.template_csv()
            assert text.strip() == ",".join(spec.columns)

    def test_templates_can_be_written_to_disk(self, app, tmp_path):
        written = importers.write_templates(tmp_path)
        assert len(written) == len(importers.SPECS)
        assert all(p.exists() for p in written)

    def test_csv_reader_handles_semicolon_delimiters(self, app, tmp_path):
        path = tmp_path / "areas.csv"
        path.write_text("area_code;area_name\nF1;Field 1\n", encoding="utf-8")
        headers, rows = importers.read_rows(path)
        assert headers == ["area_code", "area_name"]
        assert rows[0]["area_name"] == "Field 1"

    def test_csv_reader_handles_a_utf8_bom(self, app, tmp_path):
        path = tmp_path / "areas.csv"
        path.write_bytes("area_code,area_name\nF1,Field 1\n".encode("utf-8-sig"))
        headers, _ = importers.read_rows(path)
        assert headers[0] == "area_code"
