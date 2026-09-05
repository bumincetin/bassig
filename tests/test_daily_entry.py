"""The one-screen daily entry: today's button, carry-forward, and procurement
recorded from the site diary.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from app import constants as C
from app.models import (
    DailyProgress,
    DailySiteReport,
    Delivery,
    Material,
    MaterialTransaction,
    ProcurementPackage,
)
from app.services import procurement_service


@pytest.fixture()
def material(db):
    package = ProcurementPackage(package_code="PKG-01", package_name="PV Modules")
    db.session.add(package)
    db.session.flush()
    row = Material(package_id=package.id, item="PV modules 585 Wp", unit="no",
                   total_required=13965.0)
    db.session.add(row)
    db.session.commit()
    return row


class TestTodayButton:
    def test_today_creates_the_diary_on_first_use(self, app, client):
        assert DailySiteReport.query.count() == 0
        response = client.get("/daily/today", follow_redirects=True)
        assert response.status_code == 200
        report = DailySiteReport.query.one()
        assert report.report_date == date.today()
        assert report.report_number == "BAS-DSR-0001"

    def test_today_reopens_the_same_diary(self, app, client):
        client.get("/daily/today", follow_redirects=True)
        client.get("/daily/today", follow_redirects=True)
        assert DailySiteReport.query.count() == 1

    def test_a_specific_date_can_be_opened(self, app, client):
        client.get("/daily/today?date=2026-08-27", follow_redirects=True)
        assert DailySiteReport.query.one().report_date == date(2026, 8, 27)

    def test_the_button_is_on_every_page(self, app, client):
        for path in ("/", "/schedule/", "/procurement/", "/acceptance/", "/setup/"):
            page = client.get(path).get_data(as_text=True)
            assert "/daily/today" in page, f"{path} has no today button"

    def test_the_diary_links_to_the_previous_day(self, app, client, db):
        client.get("/daily/today?date=2026-09-03", follow_redirects=True)
        client.get("/daily/today?date=2026-09-04", follow_redirects=True)
        latest = DailySiteReport.query.filter_by(report_date=date(2026, 9, 4)).one()
        earlier = DailySiteReport.query.filter_by(report_date=date(2026, 9, 3)).one()
        page = client.get(f"/daily/{latest.id}").get_data(as_text=True)
        assert f"/daily/{earlier.id}" in page
        assert "Previous day" in page


class TestProgressCarriesForward:
    def _record(self, client, report_id, wbs, actual, planned=60, comments=""):
        return client.post(f"/daily/{report_id}/progress", data={
            "wbs_code": wbs, "planned_quantity": str(planned),
            "actual_quantity": str(actual), "workers": "9", "hours": "10",
            "comments": comments}, follow_redirects=True)

    def test_the_second_day_starts_from_the_first_day_total(self, app, client, db):
        client.get("/daily/today?date=2026-09-03", follow_redirects=True)
        client.get("/daily/today?date=2026-09-04", follow_redirects=True)
        first = DailySiteReport.query.filter_by(report_date=date(2026, 9, 3)).one()
        second = DailySiteReport.query.filter_by(report_date=date(2026, 9, 4)).one()

        self._record(client, first.id, "1.3.2.2", 45, comments="Rig 1 on the north row")
        self._record(client, second.id, "1.3.2.2", 70, comments="Second rig mobilised")

        rows = (DailyProgress.query.filter_by(wbs_code="1.3.2.2")
                .order_by(DailyProgress.entry_date).all())
        assert rows[0].cumulative_before == pytest.approx(0.0)
        assert rows[0].cumulative_after == pytest.approx(45.0)
        assert rows[1].cumulative_before == pytest.approx(45.0)
        assert rows[1].cumulative_after == pytest.approx(115.0)

    def test_the_explanation_is_stored_with_the_quantity(self, app, client, db):
        client.get("/daily/today", follow_redirects=True)
        report = DailySiteReport.query.one()
        self._record(client, report.id, "1.3.2.2", 45,
                     comments="Ground softer than expected on the north row.")
        entry = DailyProgress.query.one()
        assert entry.comments == "Ground softer than expected on the north row."
        assert entry.achievement_pct == pytest.approx(75.0)

    def test_a_later_entry_does_not_disturb_an_earlier_one(self, app, client, db):
        client.get("/daily/today?date=2026-09-03", follow_redirects=True)
        client.get("/daily/today?date=2026-09-04", follow_redirects=True)
        first = DailySiteReport.query.filter_by(report_date=date(2026, 9, 3)).one()
        second = DailySiteReport.query.filter_by(report_date=date(2026, 9, 4)).one()
        self._record(client, first.id, "1.3.2.2", 45)
        self._record(client, second.id, "1.3.2.2", 70)
        first_row = DailyProgress.query.filter_by(entry_date=date(2026, 9, 3)).one()
        assert first_row.actual_quantity == pytest.approx(45.0)
        assert first_row.cumulative_before == pytest.approx(0.0)


class TestDeliveryFromTheDiary:
    def test_a_delivery_updates_the_material_and_the_store(self, app, client, db, material):
        client.get("/daily/today", follow_redirects=True)
        report = DailySiteReport.query.one()
        client.post(f"/daily/{report.id}/delivery", data={
            "material_id": str(material.id), "quantity": "500",
            "accepted_quantity": "480", "rejected_quantity": "20",
            "delivery_note_reference": "DDT-0001",
            "status": "PARTIALLY ACCEPTED"}, follow_redirects=True)
        db.session.refresh(material)
        assert material.delivered == pytest.approx(500.0)
        assert material.accepted == pytest.approx(480.0)
        # Delivery is not installation.
        assert material.installed == pytest.approx(0.0)
        assert procurement_service.stock_for(material) == pytest.approx(480.0)

    def test_an_uninspected_delivery_adds_nothing_to_store(self, app, client, db, material):
        client.get("/daily/today", follow_redirects=True)
        report = DailySiteReport.query.one()
        client.post(f"/daily/{report.id}/delivery", data={
            "material_id": str(material.id), "quantity": "500",
            "delivery_note_reference": "DDT-0002"}, follow_redirects=True)
        db.session.refresh(material)
        assert material.delivered == pytest.approx(500.0)
        assert material.accepted == pytest.approx(0.0)
        assert procurement_service.stock_for(material) == pytest.approx(0.0)

    def test_deleting_a_delivery_recalculates_the_totals(self, app, client, db, material):
        client.get("/daily/today", follow_redirects=True)
        report = DailySiteReport.query.one()
        client.post(f"/daily/{report.id}/delivery", data={
            "material_id": str(material.id), "quantity": "500",
            "accepted_quantity": "500"}, follow_redirects=True)
        delivery = Delivery.query.one()
        client.post(f"/daily/deliveries/{delivery.id}/delete", follow_redirects=True)
        db.session.refresh(material)
        assert material.delivered == pytest.approx(0.0)
        assert material.actual_delivery is None

    def test_a_delivery_needs_a_material(self, app, client, db, material):
        client.get("/daily/today", follow_redirects=True)
        report = DailySiteReport.query.one()
        response = client.post(f"/daily/{report.id}/delivery",
                               data={"quantity": "500"}, follow_redirects=True)
        assert b"Select the material line" in response.data
        assert Delivery.query.count() == 0


class TestInstallationBuildsUp:
    def _install(self, client, report_id, material, quantity):
        return client.post(f"/daily/{report_id}/material", data={
            "material_id": str(material.id), "transaction_type": "INSTALLED IN WORKS",
            "quantity": str(quantity)}, follow_redirects=True)

    @pytest.fixture()
    def stocked(self, client, db, material):
        client.get("/daily/today?date=2026-09-03", follow_redirects=True)
        client.get("/daily/today?date=2026-09-04", follow_redirects=True)
        first = DailySiteReport.query.filter_by(report_date=date(2026, 9, 3)).one()
        client.post(f"/daily/{first.id}/delivery", data={
            "material_id": str(material.id), "quantity": "1000",
            "accepted_quantity": "1000"}, follow_redirects=True)
        return first

    def test_installed_accumulates_across_days(self, app, client, db, material, stocked):
        second = DailySiteReport.query.filter_by(report_date=date(2026, 9, 4)).one()
        self._install(client, stocked.id, material, 120)
        self._install(client, second.id, material, 200)
        db.session.refresh(material)
        assert material.installed == pytest.approx(320.0)

    def test_each_day_is_separately_recoverable(self, app, client, db, material, stocked):
        second = DailySiteReport.query.filter_by(report_date=date(2026, 9, 4)).one()
        self._install(client, stocked.id, material, 120)
        self._install(client, second.id, material, 200)
        assert procurement_service.installed_on(material, date(2026, 9, 3)) == pytest.approx(120.0)
        assert procurement_service.installed_on(material, date(2026, 9, 4)) == pytest.approx(200.0)

    def test_installing_does_not_deduct_from_store_twice(self, app, client, db,
                                                         material, stocked):
        client.post(f"/daily/{stocked.id}/material", data={
            "material_id": str(material.id), "transaction_type": "ISSUE TO WORKFRONT",
            "quantity": "300"}, follow_redirects=True)
        assert procurement_service.stock_for(material) == pytest.approx(700.0)
        self._install(client, stocked.id, material, 300)
        # The material left the store when it was issued, not when it was fixed.
        assert procurement_service.stock_for(material) == pytest.approx(700.0)

    def test_a_typed_installed_quantity_is_preserved_as_an_opening_balance(
            self, app, client, db, material, stocked):
        material.installed = 50.0
        db.session.commit()
        self._install(client, stocked.id, material, 120)
        db.session.refresh(material)
        assert material.installed == pytest.approx(170.0)
        opening = MaterialTransaction.query.filter_by(reference="Opening balance").one()
        assert opening.quantity == pytest.approx(50.0)

    def test_no_opening_balance_is_written_twice(self, app, client, db, material, stocked):
        material.installed = 50.0
        db.session.commit()
        self._install(client, stocked.id, material, 10)
        self._install(client, stocked.id, material, 10)
        assert MaterialTransaction.query.filter_by(reference="Opening balance").count() == 1
        db.session.refresh(material)
        assert material.installed == pytest.approx(70.0)

    def test_deleting_an_installation_recalculates_the_total(self, app, client, db,
                                                             material, stocked):
        self._install(client, stocked.id, material, 120)
        movement = MaterialTransaction.query.filter_by(
            transaction_type="INSTALLED IN WORKS").one()
        client.post(f"/daily/movements/{movement.id}/delete", follow_redirects=True)
        db.session.refresh(material)
        assert material.installed == pytest.approx(0.0)

    def test_a_movement_needs_a_quantity(self, app, client, db, material, stocked):
        response = client.post(f"/daily/{stocked.id}/material", data={
            "material_id": str(material.id),
            "transaction_type": "INSTALLED IN WORKS"}, follow_redirects=True)
        assert b"Enter the quantity" in response.data


class TestDiaryPageContents:
    def test_the_procurement_panel_is_on_the_diary(self, app, client, db, material):
        client.get("/daily/today", follow_redirects=True)
        report = DailySiteReport.query.one()
        page = client.get(f"/daily/{report.id}").get_data(as_text=True)
        assert "Deliveries" in page and "materials today" in page
        assert "Installed in the works" in page
        assert material.item in page

    def test_the_diary_explains_the_carry_forward(self, app, client):
        client.get("/daily/today", follow_redirects=True)
        report = DailySiteReport.query.one()
        page = client.get(f"/daily/{report.id}").get_data(as_text=True)
        assert "carries forward" in page

    def test_the_panel_guides_the_user_when_no_material_exists(self, app, client):
        client.get("/daily/today", follow_redirects=True)
        report = DailySiteReport.query.one()
        page = client.get(f"/daily/{report.id}").get_data(as_text=True)
        assert "No material line is registered yet" in page

    def test_the_days_movements_are_listed(self, app, client, db, material):
        client.get("/daily/today", follow_redirects=True)
        report = DailySiteReport.query.one()
        client.post(f"/daily/{report.id}/delivery", data={
            "material_id": str(material.id), "quantity": "500",
            "accepted_quantity": "500", "delivery_note_reference": "DDT-0007"},
            follow_redirects=True)
        page = client.get(f"/daily/{report.id}").get_data(as_text=True)
        assert "DDT-0007" in page
        assert "RECEIPT ACCEPTED" in page


class TestStockFormulaUnchanged:
    def test_installation_is_excluded_from_the_stock_formula(self, app, db, material):
        for movement_type, quantity in [("RECEIPT ACCEPTED", 1000),
                                        ("ISSUE TO WORKFRONT", 400),
                                        ("INSTALLED IN WORKS", 400),
                                        ("RETURN TO STORE", 50),
                                        ("ADJUSTMENT", -10)]:
            db.session.add(MaterialTransaction(
                material_id=material.id, transaction_date=date(2026, 9, 4),
                transaction_type=movement_type, quantity=quantity))
        db.session.commit()
        # 1000 received + 50 returned - 400 issued - 10 adjustment = 640
        assert procurement_service.stock_for(material) == pytest.approx(640.0)

    def test_the_install_movement_type_is_registered(self):
        assert "INSTALLED IN WORKS" in C.MATERIAL_TXN_TYPES
        assert C.MATERIAL_TXN_INSTALL == {"INSTALLED IN WORKS"}
