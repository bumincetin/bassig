#!/usr/bin/env bash
# ===================================================================
#  BASSIGNANA EPC CONTROL - start the site control system
#
#  Run with:  ./start.sh
#  Leave the terminal open while the system is in use.
#  Your data is in data/bassignana.db and survives every restart.
# ===================================================================
set -u
cd "$(dirname "$0")"

PY="${PYTHON:-python3}"
command -v "$PY" >/dev/null 2>&1 || PY=python
if ! command -v "$PY" >/dev/null 2>&1; then
  echo "Python 3.10 or newer is required but was not found."
  exit 1
fi

if ! "$PY" -c "import flask, flask_sqlalchemy, waitress, openpyxl" >/dev/null 2>&1; then
  echo "Installing the required packages (once; needs internet)."
  "$PY" -m pip install -r requirements.txt || exit 1
fi

if [ -f data/bassignana.db ]; then
  "$PY" - <<'PYEOF' 2>/dev/null || true
from app import create_app
from app.services import backup
app = create_app()
with app.app_context():
    print("  Startup backup:", backup.create_backup().name)
PYEOF
fi

exec "$PY" run.py "$@"
