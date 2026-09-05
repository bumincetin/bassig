#!/usr/bin/env bash
# BASSIGNANA EPC CONTROL -- first-time setup in a PythonAnywhere Bash console.
#
# Open Consoles -> Bash on pythonanywhere.com and paste:
#
#   bash <(curl -fsSL https://raw.githubusercontent.com/bumincetin/bassig/main/deploy/pythonanywhere_setup.sh)
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
# shellcheck disable=SC1091
source venv/bin/activate
pip install --upgrade pip >/dev/null
pip install -r requirements.txt

mkdir -p data backups static/uploads project_data/source_documents

cat <<EOM

Done. Now on the Web tab of pythonanywhere.com:

  1. "Add a new web app"  ->  Manual configuration  ->  ${PY}
  2. Code:        Source code = ${TARGET}
                  Working directory = ${TARGET}
  3. Virtualenv:  ${TARGET}/venv
  4. WSGI file:   click the link, delete its content, paste deploy/pythonanywhere_wsgi.py
                  and set USERNAME and ACCESS_PASSWORD at the top.
  5. Static files (optional, faster CSS/JS -- do NOT map /static/ as a whole):
                  /static/vendor/  ->  ${TARGET}/static/vendor
                  /static/css/     ->  ${TARGET}/static/css
                  /static/js/      ->  ${TARGET}/static/js
  6. Security:    switch "Force HTTPS" on.
  7. Press the green "Reload" button, then open https://<username>.pythonanywhere.com

Python in the WSGI drop-down must match the virtualenv: ${PY}
EOM
