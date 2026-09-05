"""The optional shared-password gate for a hosted installation.

Without BASSIGNANA_ACCESS_PASSWORD nothing changes: the site LAN stays open.
With it, every project page needs the password once per device, the health
check and the static assets stay reachable, and guessing is slowed down.
"""
from __future__ import annotations

from urllib.parse import unquote

import pytest

from app import auth, create_app, i18n
from app.config import TestConfig
from app.extensions import db as _db
from app.models import Project

PASSWORD = "bassignana-2026"


class ProtectedConfig(TestConfig):
    ACCESS_PASSWORD = PASSWORD


@pytest.fixture()
def protected():
    auth.reset_lockouts()
    application = create_app(ProtectedConfig)
    with application.app_context():
        yield application
        _db.session.remove()
    auth.reset_lockouts()


@pytest.fixture()
def pclient(protected):
    return protected.test_client()


def sign_in(client, password=PASSWORD, **query):
    path = "/login"
    if query:
        from urllib.parse import urlencode
        path += "?" + urlencode(query)
    return client.post(path, data={"password": password})


class TestOpenByDefault:
    def test_no_password_means_no_login_screen(self, client):
        assert client.get("/").status_code == 200

    def test_the_login_page_just_returns_to_the_dashboard(self, client):
        response = client.get("/login")
        assert response.status_code == 302
        assert response.headers["Location"].endswith("/")

    def test_no_sign_out_button_is_shown(self, client):
        assert "/logout" not in client.get("/").get_data(as_text=True)


class TestTheGate:
    def test_every_page_redirects_to_the_login_screen(self, pclient):
        for path in ("/", "/daily/", "/schedule/", "/setup/", "/backup/", "/data/",
                     "/reports/daily", "/daily/export.csv"):
            response = pclient.get(path)
            assert response.status_code == 302, path
            assert "/login" in response.headers["Location"], path

    def test_the_requested_page_is_remembered(self, pclient):
        response = pclient.get("/daily/?from=2026-08-01")
        assert "next=/daily/?from=2026-08-01" in unquote(response.headers["Location"])

    def test_a_post_is_refused_and_changes_nothing(self, pclient):
        before = Project.query.first().name
        response = pclient.post("/setup/project", data={"name": "Hijacked"})
        assert response.status_code == 302
        assert "/login" in response.headers["Location"]
        assert Project.query.first().name == before

    def test_the_health_check_and_static_assets_stay_open(self, pclient):
        assert pclient.get("/healthz").status_code == 200
        assert pclient.get("/static/css/app.css").status_code == 200
        assert pclient.get("/static/js/app.js").status_code == 200

    def test_photographs_are_project_records_and_are_not_open(self, pclient):
        response = pclient.get("/static/uploads/2026-09/evidence.jpg")
        assert response.status_code == 302
        assert "/login" in response.headers["Location"]

    def test_the_right_password_opens_the_site(self, pclient):
        response = sign_in(pclient)
        assert response.status_code == 302
        assert pclient.get("/").status_code == 200
        assert pclient.get("/daily/").status_code == 200

    def test_the_wrong_password_does_not(self, pclient):
        response = sign_in(pclient, "wrong")
        assert response.status_code == 200
        assert "The password is not correct." in response.get_data(as_text=True)
        assert pclient.get("/").status_code == 302

    def test_sign_in_returns_to_the_requested_page(self, pclient):
        response = sign_in(pclient, next="/schedule/lookahead")
        assert response.headers["Location"].endswith("/schedule/lookahead")

    @pytest.mark.parametrize("target", ["https://evil.example/", "//evil.example/x",
                                        "\\\\evil.example", "javascript:alert(1)"])
    def test_a_destination_outside_the_application_is_ignored(self, pclient, target):
        response = sign_in(pclient, next=target)
        assert response.status_code == 302
        assert "evil" not in response.headers["Location"]
        assert "javascript" not in response.headers["Location"]

    def test_sign_out_closes_the_session(self, pclient):
        sign_in(pclient)
        assert "/logout" in pclient.get("/").get_data(as_text=True)
        response = pclient.post("/logout")
        assert response.status_code == 302
        assert pclient.get("/").status_code == 302

    def test_repeated_failures_lock_the_address_out(self, pclient, protected):
        for _ in range(protected.config["LOGIN_MAX_FAILURES"]):
            sign_in(pclient, "wrong")
        # Even the right password is refused while the lockout lasts.
        response = sign_in(pclient)
        assert response.status_code == 200
        assert "Too many failed attempts" in response.get_data(as_text=True)
        assert pclient.get("/").status_code == 302

    def test_a_successful_sign_in_clears_earlier_failures(self, pclient, protected):
        for _ in range(protected.config["LOGIN_MAX_FAILURES"] - 1):
            sign_in(pclient, "wrong")
        assert sign_in(pclient).status_code == 302
        pclient.post("/logout")
        for _ in range(protected.config["LOGIN_MAX_FAILURES"] - 1):
            sign_in(pclient, "wrong")
        assert sign_in(pclient).status_code == 302

    def test_the_password_never_appears_in_the_page(self, pclient):
        assert PASSWORD not in pclient.get("/login").get_data(as_text=True)
        assert PASSWORD not in sign_in(pclient, "wrong").get_data(as_text=True)


class TestTheLoginScreenIsTranslated:
    @pytest.mark.parametrize("code", ["en", "tr", "it"])
    def test_it_renders_in_every_language(self, pclient, code):
        if code != "en":
            i18n._MISSING[code].clear()
        response = pclient.get(f"/login?lang={code}")
        assert response.status_code == 200
        page = response.get_data(as_text=True)
        assert f'<html lang="{code}"' in page
        assert i18n.translate("Sign in", language=code) in page
        if code != "en":
            assert sorted(i18n._MISSING[code]) == []

    def test_the_error_is_translated(self, pclient):
        response = pclient.post("/login?lang=it", data={"password": "wrong"})
        assert i18n.translate("The password is not correct.", language="it") in \
            response.get_data(as_text=True)

    def test_the_language_switcher_keeps_the_destination(self, pclient):
        page = unquote(pclient.get("/login?next=/daily/").get_data(as_text=True))
        assert "next=/daily/" in page
        for code in i18n.LANGUAGES:
            assert f"lang={code}" in page

    def test_the_sign_out_button_is_translated(self, pclient):
        sign_in(pclient)
        page = pclient.get("/?lang=tr").get_data(as_text=True)
        assert i18n.translate("Sign out", language="tr") in page
