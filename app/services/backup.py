"""Database backup, integrity check and restore guidance."""
from __future__ import annotations

import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

from flask import current_app

from app.extensions import db
from app.i18n import translate as t


def database_path():
    uri = current_app.config["SQLALCHEMY_DATABASE_URI"]
    if not uri.startswith("sqlite:///"):
        return None
    return Path(uri.replace("sqlite:///", "", 1))


def backup_dir():
    path = Path(current_app.config["BACKUP_DIR"])
    path.mkdir(parents=True, exist_ok=True)
    return path


def create_backup():
    """Timestamped copy of the live database, taken through SQLite itself."""
    source = database_path()
    if source is None or not source.exists():
        raise FileNotFoundError(t("The live database file could not be located."))

    db.session.commit()
    target = backup_dir() / f"bassignana_{datetime.now():%Y-%m-%d_%H%M%S}.db"

    # sqlite3 backup API produces a consistent copy even with open connections.
    with sqlite3.connect(str(source)) as src_conn, sqlite3.connect(str(target)) as dst_conn:
        src_conn.backup(dst_conn)
    return target


def list_backups():
    rows = []
    for path in sorted(backup_dir().glob("bassignana_*.db"), reverse=True):
        stat = path.stat()
        rows.append({
            "name": path.name,
            "path": path,
            "size_bytes": stat.st_size,
            "size_mb": stat.st_size / (1024 * 1024),
            "created": datetime.fromtimestamp(stat.st_mtime),
            "integrity": None,
        })
    return rows


def verify_backup(path):
    """Run SQLite's own integrity check against a backup file."""
    path = Path(path)
    if not path.exists():
        return False, "File not found."
    try:
        with sqlite3.connect(str(path)) as conn:
            result = conn.execute("PRAGMA integrity_check").fetchone()
            tables = conn.execute(
                "SELECT count(*) FROM sqlite_master WHERE type='table'"
            ).fetchone()
        ok = bool(result) and result[0] == "ok"
        return ok, f"integrity_check={result[0] if result else 'no result'}; " \
                   f"{tables[0] if tables else 0} tables"
    except sqlite3.DatabaseError as exc:
        return False, f"SQLite reported: {exc}"


def delete_backup(name):
    path = backup_dir() / Path(name).name
    if path.exists() and path.parent == backup_dir():
        path.unlink()
        return True
    return False


def upload_stats():
    """Size of the evidence store, needed for manual migration."""
    upload_dir = Path(current_app.config["UPLOAD_DIR"])
    files = [p for p in upload_dir.rglob("*") if p.is_file()]
    total = sum(p.stat().st_size for p in files)
    return {
        "path": upload_dir,
        "file_count": len(files),
        "total_bytes": total,
        "total_mb": total / (1024 * 1024),
    }


def source_document_stats():
    directory = Path(current_app.config["SOURCE_DOC_DIR"])
    files = [p for p in directory.rglob("*") if p.is_file()]
    total = sum(p.stat().st_size for p in files)
    return {
        "path": directory,
        "file_count": len(files),
        "total_bytes": total,
        "total_mb": total / (1024 * 1024),
    }


RESTORE_INSTRUCTIONS = [
    "Stop the application (close the terminal window running `python run.py`).",
    "Open the `backups/` folder and pick the backup you want to restore.",
    "Rename the current `data/bassignana.db` to `data/bassignana_before_restore.db` "
    "so you can go back if needed.",
    "Copy the chosen backup file into `data/` and rename it to `bassignana.db`.",
    "Copy back the matching `static/uploads/` folder if you are restoring onto a different "
    "machine -- photographs and evidence files are stored there, not in the database.",
    "Copy back `project_data/source_documents/` so registered source documents remain "
    "reachable from their register entries.",
    "Start the application again with `python run.py` and check the Dashboard "
    "and Data Import history.",
]

MIGRATION_INSTRUCTIONS = [
    "Copy the whole project folder to the new machine, or at minimum: "
    "`data/bassignana.db`, `static/uploads/`, `project_data/` and `backups/`.",
    "Install Python 3.10 or newer on the new machine.",
    "Run `pip install -r requirements.txt` in the project folder.",
    "Run `python run.py` and open the printed LAN address from other devices.",
]
