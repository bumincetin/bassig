"""Running on a shared server.

The application must be able to keep every writable folder on one persistent
volume, serve photographs from wherever that is, take its port from the
hosting platform and choose a SQLite journal mode that suits the file system.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import text

from app import create_app
from app.config import TestConfig
from app.extensions import db as _db

ROOT = Path(__file__).resolve().parent.parent

_PRINT_CONFIG = (
    "import json; from app.config import Config as c; "
    "print(json.dumps({k: str(getattr(c, k)) for k in ("
    "'DATA_DIR', 'UPLOAD_DIR', 'BACKUP_DIR', 'SOURCE_DOC_DIR', "
    "'SQLALCHEMY_DATABASE_URI', 'SQLITE_JOURNAL_MODE', 'ACCESS_PASSWORD', "
    "'SESSION_COOKIE_SECURE', 'BEHIND_PROXY')}))"
)


def config_with(**env):
    """Evaluate app.config in a fresh interpreter with the given environment."""
    environment = {k: v for k, v in os.environ.items() if not k.startswith("BASSIGNANA_")}
    environment.update(env)
    result = subprocess.run([sys.executable, "-c", _PRINT_CONFIG], cwd=ROOT,
                            env=environment, capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


class TestRelocatableDirectories:
    def test_data_dir_moves_every_writable_folder(self, tmp_path):
        live = (tmp_path / "live").resolve()
        values = config_with(BASSIGNANA_DATA_DIR=str(live))
        assert Path(values["DATA_DIR"]) == live
        assert Path(values["UPLOAD_DIR"]) == live / "uploads"
        assert Path(values["BACKUP_DIR"]) == live / "backups"
        assert Path(values["SOURCE_DOC_DIR"]) == live / "source_documents"
        assert values["SQLALCHEMY_DATABASE_URI"].endswith("/live/bassignana.db")
        for name in ("uploads", "backups", "source_documents"):
            assert (live / name).is_dir(), name

    def test_each_folder_can_be_placed_individually(self, tmp_path):
        values = config_with(BASSIGNANA_BACKUP_DIR=str(tmp_path / "b"),
                             BASSIGNANA_UPLOAD_DIR=str(tmp_path / "u"))
        assert Path(values["BACKUP_DIR"]) == (tmp_path / "b").resolve()
        assert Path(values["UPLOAD_DIR"]) == (tmp_path / "u").resolve()
        # Everything else stays where the local installation keeps it.
        assert Path(values["DATA_DIR"]) == ROOT / "data"
        assert Path(values["SOURCE_DOC_DIR"]) == ROOT / "project_data" / "source_documents"

    def test_the_defaults_are_the_local_installation(self):
        values = config_with()
        assert Path(values["DATA_DIR"]) == ROOT / "data"
        assert Path(values["UPLOAD_DIR"]) == ROOT / "static" / "uploads"
        assert Path(values["BACKUP_DIR"]) == ROOT / "backups"
        assert values["SQLITE_JOURNAL_MODE"] == "WAL"
        assert values["ACCESS_PASSWORD"] == ""
        assert values["SESSION_COOKIE_SECURE"] == "False"
        assert values["BEHIND_PROXY"] == "False"

    def test_hosting_settings_come_from_the_environment(self):
        values = config_with(BASSIGNANA_SQLITE_JOURNAL_MODE="delete",
                             BASSIGNANA_ACCESS_PASSWORD="  shared-secret  ",
                             BASSIGNANA_HTTPS="1", BASSIGNANA_BEHIND_PROXY="yes")
        assert values["SQLITE_JOURNAL_MODE"] == "DELETE"
        assert values["ACCESS_PASSWORD"] == "shared-secret"
        assert values["SESSION_COOKIE_SECURE"] == "True"
        assert values["BEHIND_PROXY"] == "True"


class TestUploadsRoute:
    def test_photographs_are_served_from_the_configured_folder(self, tmp_path):
        evidence = tmp_path / "evidence"
        (evidence / "2026-09").mkdir(parents=True)
        (evidence / "2026-09" / "pile.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")

        class Cfg(TestConfig):
            UPLOAD_DIR = evidence

        application = create_app(Cfg)
        with application.app_context():
            client = application.test_client()
            response = client.get("/static/uploads/2026-09/pile.png")
            assert response.status_code == 200
            assert response.data.startswith(b"\x89PNG")
            # The generic static route still serves the bundled assets.
            assert client.get("/static/css/app.css").status_code == 200
            assert client.get("/static/uploads/2026-09/missing.png").status_code == 404
            _db.session.remove()

    def test_the_folder_cannot_be_escaped(self, tmp_path):
        evidence = tmp_path / "evidence"
        evidence.mkdir()
        (tmp_path / "outside.txt").write_text("secret", encoding="utf-8")

        class Cfg(TestConfig):
            UPLOAD_DIR = evidence

        application = create_app(Cfg)
        with application.app_context():
            client = application.test_client()
            for path in ("/static/uploads/../outside.txt", "/static/uploads/%2e%2e/outside.txt"):
                response = client.get(path)
                assert response.status_code != 200 or b"secret" not in response.data
            _db.session.remove()


class TestJournalMode:
    def _mode(self, tmp_path, wanted):
        class Cfg(TestConfig):
            SQLALCHEMY_DATABASE_URI = f"sqlite:///{(tmp_path / 'journal.db').as_posix()}"
            SQLITE_JOURNAL_MODE = wanted

        application = create_app(Cfg)
        with application.app_context():
            with _db.engine.connect() as connection:
                mode = connection.execute(text("PRAGMA journal_mode")).scalar()
            _db.session.remove()
            _db.engine.dispose()
        return mode.lower()

    def test_wal_is_the_default(self, tmp_path):
        assert self._mode(tmp_path, "WAL") == "wal"

    def test_delete_mode_is_honoured_for_network_file_systems(self, tmp_path):
        assert self._mode(tmp_path, "DELETE") == "delete"

    def test_an_unknown_mode_falls_back_to_wal(self, tmp_path):
        assert self._mode(tmp_path, "nonsense") == "wal"


class TestPlatformPort:
    def test_the_platform_port_is_used_when_nothing_else_is_set(self, monkeypatch):
        import run
        monkeypatch.delenv("BASSIGNANA_PORT", raising=False)
        monkeypatch.setenv("PORT", "8123")
        assert run.default_port() == 8123

    def test_the_explicit_port_wins(self, monkeypatch):
        import run
        monkeypatch.setenv("BASSIGNANA_PORT", "5055")
        monkeypatch.setenv("PORT", "8123")
        assert run.default_port() == 5055

    def test_the_local_default_is_5000(self, monkeypatch):
        import run
        monkeypatch.delenv("BASSIGNANA_PORT", raising=False)
        monkeypatch.delenv("PORT", raising=False)
        assert run.default_port() == 5000


class TestWsgiEntryPoint:
    def test_the_module_exposes_an_application(self):
        source = (ROOT / "wsgi.py").read_text(encoding="utf-8")
        assert "application = create_app()" in source
