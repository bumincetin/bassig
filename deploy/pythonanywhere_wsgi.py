# BASSIGNANA EPC CONTROL -- WSGI file for PythonAnywhere.
#
# Paste this whole file into the WSGI configuration file that the Web tab
# links to (it is called /var/www/<username>_pythonanywhere_com_wsgi.py),
# replacing everything that is there. Then edit the three values below and
# press "Reload" on the Web tab. Full instructions: deploy/HOSTING.md
import os
import sys

# 1. Your PythonAnywhere username (the site will be https://<USERNAME>.pythonanywhere.com).
USERNAME = "yourusername"

# 2. The shared password every employee will type once per device.
ACCESS_PASSWORD = "change-this-to-a-long-shared-password"

# 3. Where the repository was cloned (leave as is if you followed HOSTING.md).
PROJECT_DIR = f"/home/{USERNAME}/bassignana"

os.environ.setdefault("BASSIGNANA_ACCESS_PASSWORD", ACCESS_PASSWORD)
# PythonAnywhere terminates HTTPS in front of the application. Turn on
# "Force HTTPS" on the Web tab so that the Secure cookie always reaches us.
os.environ.setdefault("BASSIGNANA_BEHIND_PROXY", "1")
os.environ.setdefault("BASSIGNANA_HTTPS", "1")
# PythonAnywhere keeps files on a network file system, where SQLite's WAL
# mode cannot be used. DELETE is the classic rollback journal and is safe there.
os.environ.setdefault("BASSIGNANA_SQLITE_JOURNAL_MODE", "DELETE")

if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from app import create_app  # noqa: E402

application = create_app()
