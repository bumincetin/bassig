"""Database backup, verification and restore guidance."""
from __future__ import annotations

from pathlib import Path

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)

from app.i18n import translate as t

from app.routes._helpers import form_str
from app.services import backup as backup_service

bp = Blueprint("backup", __name__, url_prefix="/backup")


@bp.route("/")
def index():
    backups = backup_service.list_backups()
    verified = request.args.get("verified")
    for row in backups:
        if verified and row["name"] == verified:
            row["integrity"] = backup_service.verify_backup(row["path"])
    return render_template(
        "backup/index.html",
        backups=backups,
        database=backup_service.database_path(),
        database_size_mb=(backup_service.database_path().stat().st_size / (1024 * 1024)
                          if backup_service.database_path()
                          and backup_service.database_path().exists() else 0.0),
        uploads=backup_service.upload_stats(),
        sources=backup_service.source_document_stats(),
        restore=backup_service.RESTORE_INSTRUCTIONS,
        migration=backup_service.MIGRATION_INSTRUCTIONS,
        verified=verified,
    )


@bp.route("/create", methods=["POST"])
def create():
    try:
        path = backup_service.create_backup()
    except FileNotFoundError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("backup.index"))
    ok, detail = backup_service.verify_backup(path)
    if ok:
        flash(t("Backup created: {name} ({detail}).", name=path.name, detail=detail), "success")
    else:
        flash(t("Backup created as {name} but the integrity check reported: {detail}", name=path.name, detail=detail),
              "warning")
    return redirect(url_for("backup.index", verified=path.name))


@bp.route("/verify/<name>", methods=["POST"])
def verify(name):
    path = backup_service.backup_dir() / Path(name).name
    ok, detail = backup_service.verify_backup(path)
    flash(t("Integrity check on {name}: {result} - {detail}", name=Path(name).name,
            result=t("PASSED") if ok else t("FAILED"), detail=detail),
          "success" if ok else "danger")
    return redirect(url_for("backup.index", verified=Path(name).name))


@bp.route("/download/<name>")
def download(name):
    return send_from_directory(current_app.config["BACKUP_DIR"], Path(name).name,
                               as_attachment=True)


@bp.route("/delete/<name>", methods=["POST"])
def delete(name):
    confirmation = form_str("confirm")
    if confirmation != Path(name).name:
        flash(t("Type the exact backup file name to confirm deletion. Nothing was deleted."),
              "danger")
        return redirect(url_for("backup.index"))
    if backup_service.delete_backup(name):
        flash(t("Backup {name} deleted permanently.", name=Path(name).name), "warning")
    else:
        flash(t("That backup could not be found."), "danger")
    return redirect(url_for("backup.index"))
