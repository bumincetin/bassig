"""File logging for an unattended site installation.

The server usually runs minimised in a corner of the site office. When
something goes wrong nobody is watching the console, so everything of
consequence is written to a rotating log file that can be sent on.
"""
from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

LOG_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def init_app(app):
    log_dir = Path(app.config["DATA_DIR"]) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "bassignana.log"

    formatter = logging.Formatter(LOG_FORMAT, DATE_FORMAT)

    file_handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=2 * 1024 * 1024, backupCount=5, encoding="utf-8")
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.INFO)

    root = logging.getLogger()
    # Replace any handler this function added before, so repeated app creation
    # in tests does not multiply log lines.
    for handler in list(root.handlers):
        if getattr(handler, "_bassignana", False):
            root.removeHandler(handler)
    file_handler._bassignana = True
    root.addHandler(file_handler)
    root.setLevel(logging.INFO)

    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    app.logger.setLevel(logging.INFO)
    app.config["LOG_PATH"] = log_path
    return log_path
