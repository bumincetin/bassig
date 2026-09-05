"""Application configuration for BASSIGNANA EPC CONTROL.

Everything is local by default: SQLite on disk, uploads on disk, no external
service of any kind. A hosted installation (one shared server for the whole
company instead of one site PC) can relocate every writable directory onto a
persistent volume and require a shared password, using environment variables
only -- nothing in the code changes between the two ways of running it.

    BASSIGNANA_DATA_DIR             database, logs, secret key, import workspace.
                                    When set, uploads, backups and source
                                    documents default to sub-folders of it, so a
                                    single mounted volume holds all live data.
    BASSIGNANA_UPLOAD_DIR           site photographs and evidence files
    BASSIGNANA_BACKUP_DIR           timestamped database backups
    BASSIGNANA_SOURCE_DOC_DIR       registered source-document files
    BASSIGNANA_DATABASE_URI         database location, if not DATA_DIR/bassignana.db
    BASSIGNANA_ACCESS_PASSWORD      shared password required to open the site.
                                    Empty (the default) keeps the open LAN mode.
    BASSIGNANA_BEHIND_PROXY         "1" when a reverse proxy or hosting platform
                                    terminates HTTPS in front of the application
    BASSIGNANA_HTTPS                "1" to mark the session cookie Secure
    BASSIGNANA_SQLITE_JOURNAL_MODE  WAL (default) or DELETE on network file systems
    BASSIGNANA_SECRET_KEY           overrides the generated, persisted secret key
"""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _env_flag(name, default=False):
    value = os.environ.get(name)
    if value is None or not value.strip():
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_path(name, default):
    value = (os.environ.get(name) or "").strip()
    return Path(value).expanduser().resolve() if value else Path(default)


_DATA_DIR_OVERRIDDEN = bool((os.environ.get("BASSIGNANA_DATA_DIR") or "").strip())

DATA_DIR = _env_path("BASSIGNANA_DATA_DIR", BASE_DIR / "data")
UPLOAD_DIR = _env_path(
    "BASSIGNANA_UPLOAD_DIR",
    DATA_DIR / "uploads" if _DATA_DIR_OVERRIDDEN else BASE_DIR / "static" / "uploads")
BACKUP_DIR = _env_path(
    "BASSIGNANA_BACKUP_DIR",
    DATA_DIR / "backups" if _DATA_DIR_OVERRIDDEN else BASE_DIR / "backups")
SOURCE_DOC_DIR = _env_path(
    "BASSIGNANA_SOURCE_DOC_DIR",
    DATA_DIR / "source_documents" if _DATA_DIR_OVERRIDDEN
    else BASE_DIR / "project_data" / "source_documents")
IMPORT_TEMPLATE_DIR = BASE_DIR / "project_data" / "import_templates"
IMPORT_READY_DIR = BASE_DIR / "project_data" / "import_ready"

for _d in (DATA_DIR, UPLOAD_DIR, BACKUP_DIR, SOURCE_DOC_DIR, IMPORT_TEMPLATE_DIR, IMPORT_READY_DIR):
    _d.mkdir(parents=True, exist_ok=True)


class Config:
    SECRET_KEY = os.environ.get("BASSIGNANA_SECRET_KEY", "bassignana-epc-control-local")
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "BASSIGNANA_DATABASE_URI", f"sqlite:///{(DATA_DIR / 'bassignana.db').as_posix()}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}

    #: WAL lets the site team read while somebody else writes. Some hosting
    #: providers keep files on a network file system that cannot share WAL's
    #: memory-mapped index; DELETE (SQLite's classic rollback journal) is the
    #: right choice there.
    SQLITE_JOURNAL_MODE = (os.environ.get("BASSIGNANA_SQLITE_JOURNAL_MODE") or "WAL").strip().upper()

    #: Shared password for a hosted installation. Empty means no login screen,
    #: which is the intended behaviour on a private site LAN.
    ACCESS_PASSWORD = (os.environ.get("BASSIGNANA_ACCESS_PASSWORD") or "").strip()
    #: Seconds to wait before answering a wrong password, to slow down guessing.
    LOGIN_FAILURE_DELAY = 0.5
    #: Failed attempts from one address before it is locked out, and for how long.
    LOGIN_MAX_FAILURES = 8
    LOGIN_LOCKOUT_SECONDS = 300

    BEHIND_PROXY = _env_flag("BASSIGNANA_BEHIND_PROXY")
    SESSION_COOKIE_SECURE = _env_flag("BASSIGNANA_HTTPS")

    MAX_CONTENT_LENGTH = 64 * 1024 * 1024  # 64 MB per request (site photos)
    ALLOWED_PHOTO_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
    ALLOWED_IMPORT_EXT = {".csv", ".xlsx", ".xlsm"}
    ALLOWED_DOC_EXT = {
        ".pdf", ".csv", ".xlsx", ".xlsm", ".xls", ".docx", ".doc",
        ".dwg", ".dxf", ".png", ".jpg", ".jpeg", ".txt", ".zip",
    }

    BASE_DIR = BASE_DIR
    DATA_DIR = DATA_DIR
    UPLOAD_DIR = UPLOAD_DIR
    BACKUP_DIR = BACKUP_DIR
    SOURCE_DOC_DIR = SOURCE_DOC_DIR
    IMPORT_TEMPLATE_DIR = IMPORT_TEMPLATE_DIR
    IMPORT_READY_DIR = IMPORT_READY_DIR

    JSON_SORT_KEYS = False


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    WTF_CSRF_ENABLED = False
    ACCESS_PASSWORD = ""
    LOGIN_FAILURE_DELAY = 0
    BEHIND_PROXY = False
    SESSION_COOKIE_SECURE = False
