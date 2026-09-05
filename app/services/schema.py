"""Lightweight SQLite schema management.

`db.create_all()` creates missing tables but never alters existing ones, so an
installation that has been in use since an earlier build would silently lose new
columns. Alembic is deliberately not used: it would add a dependency, a
migrations directory and a command-line step to a system that has to be
installable with one `pip install` and startable with one `python run.py`.

Instead this module reconciles the live SQLite schema with the models on every
start: it adds missing columns and indexes, and records a schema version. Every
operation is additive and idempotent -- no column is ever dropped or retyped, so
no data can be lost by starting a newer build against an older database.
"""
from __future__ import annotations

import logging

from flask import current_app
from sqlalchemy import inspect, text

from app.extensions import db

logger = logging.getLogger(__name__)

#: Bumped whenever the models change in a way that needs reconciling.
SCHEMA_VERSION = 2

#: Journal modes SQLite accepts. WAL is the default; DELETE suits a network
#: file system, where WAL's shared-memory index cannot be used.
JOURNAL_MODES = {"WAL", "DELETE", "TRUNCATE", "PERSIST", "MEMORY"}

_SQLITE_TYPES = {
    "INTEGER": "INTEGER",
    "BIGINT": "INTEGER",
    "SMALLINT": "INTEGER",
    "BOOLEAN": "BOOLEAN",
    "FLOAT": "FLOAT",
    "NUMERIC": "NUMERIC",
    "DATE": "DATE",
    "DATETIME": "DATETIME",
    "TEXT": "TEXT",
}


def _column_sql_type(column):
    """SQLite column type for a SQLAlchemy column."""
    try:
        compiled = column.type.compile(dialect=db.engine.dialect)
    except Exception:  # pragma: no cover - defensive
        return "TEXT"
    upper = compiled.upper()
    for prefix, mapped in _SQLITE_TYPES.items():
        if upper.startswith(prefix):
            return mapped
    if upper.startswith("VARCHAR"):
        return compiled
    return compiled


def _default_clause(column):
    """A literal DEFAULT for a NOT NULL column being added to existing rows."""
    default = column.default
    if default is None or getattr(default, "is_callable", False):
        return None
    value = getattr(default, "arg", None)
    if value is None or callable(value):
        return None
    if isinstance(value, bool):
        return f"DEFAULT {1 if value else 0}"
    if isinstance(value, (int, float)):
        return f"DEFAULT {value}"
    if isinstance(value, str):
        escaped = value.replace("'", "''")
        return f"DEFAULT '{escaped}'"
    return None


def ensure_schema():
    """Reconcile the live schema with the models. Returns a change report."""
    inspector = inspect(db.engine)
    existing_tables = set(inspector.get_table_names())
    added_columns, added_indexes, created_tables = [], [], []

    for table in db.metadata.sorted_tables:
        if table.name not in existing_tables:
            table.create(bind=db.engine, checkfirst=True)
            created_tables.append(table.name)
            continue

        present = {c["name"] for c in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in present:
                continue
            parts = [f'ALTER TABLE "{table.name}"',
                     f'ADD COLUMN "{column.name}"',
                     _column_sql_type(column)]
            # A NOT NULL column can only be added to a populated table when it
            # carries a literal default, so anything else is added as nullable.
            default = _default_clause(column)
            if default:
                parts.append(default)
                if not column.nullable:
                    parts.append("NOT NULL")
            statement = " ".join(parts)
            with db.engine.begin() as connection:
                connection.execute(text(statement))
            added_columns.append(f"{table.name}.{column.name}")
            logger.info("schema: added column %s.%s", table.name, column.name)

        present_indexes = {i["name"] for i in inspector.get_indexes(table.name)}
        for index in table.indexes:
            if index.name in present_indexes:
                continue
            try:
                index.create(bind=db.engine)
                added_indexes.append(index.name)
                logger.info("schema: added index %s", index.name)
            except Exception as exc:  # pragma: no cover - non-fatal
                logger.warning("schema: could not create index %s: %s", index.name, exc)

    _record_version()
    return {
        "created_tables": created_tables,
        "added_columns": added_columns,
        "added_indexes": added_indexes,
        "version": SCHEMA_VERSION,
    }


def _record_version():
    with db.engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE IF NOT EXISTS schema_version ("
            "  version INTEGER NOT NULL,"
            "  applied_at TEXT NOT NULL"
            ")"
        ))
        row = connection.execute(text("SELECT MAX(version) FROM schema_version")).scalar()
        if row is None or row < SCHEMA_VERSION:
            connection.execute(
                text("INSERT INTO schema_version (version, applied_at) "
                     "VALUES (:v, datetime('now'))"),
                {"v": SCHEMA_VERSION},
            )


def current_version():
    try:
        with db.engine.connect() as connection:
            return connection.execute(text("SELECT MAX(version) FROM schema_version")).scalar()
    except Exception:  # pragma: no cover - table may not exist yet
        return None


def apply_pragmas():
    """Durability and concurrency settings for a shared installation.

    Returns the journal mode SQLite actually selected, or None for a
    non-SQLite database.
    """
    uri = str(db.engine.url)
    if not uri.startswith("sqlite"):
        return None
    wanted = str(current_app.config.get("SQLITE_JOURNAL_MODE") or "WAL").strip().upper()
    if wanted not in JOURNAL_MODES:
        logger.warning("schema: unknown SQLITE_JOURNAL_MODE %r, using WAL", wanted)
        wanted = "WAL"
    with db.engine.begin() as connection:
        # WAL lets the site team read while somebody else is writing.
        effective = connection.execute(text(f"PRAGMA journal_mode={wanted}")).scalar()
        connection.execute(text("PRAGMA synchronous=NORMAL"))
        connection.execute(text("PRAGMA foreign_keys=ON"))
        connection.execute(text("PRAGMA busy_timeout=10000"))
    effective = str(effective or "").upper()
    if effective not in {wanted, "MEMORY"}:
        logger.warning("schema: asked for journal mode %s, SQLite selected %s",
                       wanted, effective)
    return effective
