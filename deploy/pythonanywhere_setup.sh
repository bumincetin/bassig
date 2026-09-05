#!/usr/bin/env bash
# BASSIGNANA EPC CONTROL -- first-time setup in a PythonAnywhere Bash console.
#
# Open Consoles -> Bash on pythonanywhere.com and paste these two lines:
#
#   curl -fsSL -o ~/bassignana_setup.sh https://raw.githubusercontent.com/bumincetin/bassig/main/deploy/pythonanywhere_setup.sh
#   bash ~/bassignana_setup.sh
#
# Download first, run second. A browser terminal that swallows the first word
# of a pasted line turns "bash <(curl ...)" into a confusing
# "/dev/fd/15: Permission denied"; this form simply fails safely.
#
# It clones the repository into ~/bassignana, creates a virtualenv and
# installs the requirements. Afterwards follow the Web-tab steps in
# deploy/HOSTING.md (they take about five minutes).
set -euo pipefail

REPO="${BASSIGNANA_REPO:-https://github.com/bumincetin/bassig.git}"
TARGET="${HOME}/bassignana"

if [ -d "${TARGET}/.git" ]; then
  echo "Updating the existing checkout in ${TARGET}"
  git -C "${TARGET}" pull --ff-only
else
  echo "Cloning ${REPO} into ${TARGET}"
  git clone "${REPO}" "${TARGET}"
fi

cd "${TARGET}"

# Pick the newest Python 3 available on this PythonAnywhere system image.
PY=""
for candidate in python3.13 python3.12 python3.11 python3.10; do
  if command -v "${candidate}" >/dev/null 2>&1; then PY="${candidate}"; break; fi
done
if [ -z "${PY}" ]; then
  echo "No Python 3.10+ interpreter was found." >&2
  exit 1
fi
echo "Using ${PY} ($(${PY} --version))"

if [ ! -d venv ]; then
  "${PY}" -m venv venv
fi
# The virtualenv's own pip is called directly rather than activating the
# environment: `source venv/bin/activate` can trip over `set -u` on some
# system images, and this cannot.
./venv/bin/python -m pip install --upgrade pip >/dev/null
./venv/bin/python -m pip install -r requirements.txt

mkdir -p data backups static/uploads project_data/source_documents

# The web app's Python version must match the virtualenv's, and the deployer
# needs it as X.Y.
PY_XY="$(./venv/bin/python -c 'import sys; print("%d.%d" % sys.version_info[:2])')"

echo
# importlib.metadata rather than each package's __version__: the attribute is
# deprecated in Flask 3.2 and prints a warning that reads like a failure.
./venv/bin/python -c "
from importlib.metadata import version
import app  # proves the application itself imports, not just its dependencies
print('Requirements installed: ' + ', '.join(
    '%s %s' % (name, version(name))
    for name in ('Flask', 'Flask-SQLAlchemy', 'SQLAlchemy', 'openpyxl')))
print('BASSIGNANA EPC CONTROL v%s imports correctly.' % app.__version__)"

USER_NAME="$(basename "${HOME}")"

cat <<EOM

Done. The code and its requirements are in place on Python ${PY_XY}.

NEXT: finish the deployment from your own PC, in the project folder, with

  python deploy/pythonanywhere_deploy.py \\
      --username ${USER_NAME} \\
      --token    YOUR_API_TOKEN \\
      --password 'the shared password for the site' \\
      --python-version ${PY_XY} \\
      --database data/bassignana.db

Create the token on this site under Account -> API token. That command makes
the web app, writes the WSGI file, sets the virtualenv, maps the static
folders, turns on Force HTTPS, uploads the project record and reloads.

Or do it by hand on the Web tab instead:

  1. "Add a new web app"  ->  Manual configuration  ->  Python ${PY_XY}
  2. Code:        Source code = ${TARGET}
                  Working directory = ${TARGET}
  3. Virtualenv:  ${TARGET}/venv
  4. WSGI file:   click the link, delete its content, paste deploy/pythonanywhere_wsgi.py
                  and set USERNAME and ACCESS_PASSWORD at the top.
  5. Static files (optional, faster CSS/JS -- do NOT map /static/ as a whole,
                  or photographs would bypass the access password):
                  /static/vendor/  ->  ${TARGET}/static/vendor
                  /static/css/     ->  ${TARGET}/static/css
                  /static/js/      ->  ${TARGET}/static/js
  6. Security:    switch "Force HTTPS" on.
  7. Press the green "Reload" button, then open https://${USER_NAME}.pythonanywhere.com
EOM
