"""WSGI entry point for hosting platforms.

PythonAnywhere, gunicorn, uWSGI, mod_wsgi and most platform-as-a-service
providers look for a module exposing an `application` object:

    gunicorn --bind 0.0.0.0:8080 --workers 1 --threads 8 wsgi:application

Keep a single worker process with several threads: the database is SQLite,
which is happiest with one process writing to it. Configuration comes from
the BASSIGNANA_* environment variables described in app/config.py.
"""
from __future__ import annotations

from app import create_app

application = create_app()
app = application  # some platforms look for this name instead
