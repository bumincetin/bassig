#!/usr/bin/env python3
"""Deploy BASSIGNANA EPC CONTROL to PythonAnywhere through their REST API.

This does every Web-tab step for you: it creates the web app, writes the WSGI
file with your access password, points it at the checkout and the virtualenv,
adds the static-file mappings, turns on Force HTTPS, uploads the live database
and reloads the site. It finishes by asking the running site for /healthz and
printing the address.

Two things it deliberately cannot do, because PythonAnywhere does not allow
them over the API:

* create the account -- signing up needs an e-mail confirmation and a CAPTCHA;
* run `pip install` -- the API can create a console but cannot start one
  ("Only connecting to the console in a browser will do that"), so the
  requirements have to be installed once from a Bash console in the browser.
  `deploy/pythonanywhere_setup.sh` is that one paste.

So the order is:

    1. Sign up at pythonanywhere.com (free Beginner plan, no card).
    2. Consoles -> Bash, paste the one line from deploy/HOSTING.md.
    3. Account -> API token -> Create a new API token.
    4. Run this script:

           python deploy/pythonanywhere_deploy.py \
               --username YOURNAME \
               --token    YOUR_API_TOKEN \
               --password 'the shared password for the site' \
               --database data/bassignana.db

Re-running it is safe: an existing web app is updated in place rather than
duplicated, and the database is only uploaded when --database is given.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

#: PythonAnywhere runs two independent installations with separate accounts.
API_HOSTS = {
    "www": "https://www.pythonanywhere.com",
    "eu": "https://eu.pythonanywhere.com",
}

#: Only these three prefixes are mapped to the static-file server. /static/ as
#: a whole must NOT be mapped: uploads/ lives under it and photographs are
#: project records that have to stay behind the access password.
STATIC_MAPPINGS = [
    ("/static/vendor/", "static/vendor"),
    ("/static/css/", "static/css"),
    ("/static/js/", "static/js"),
]

WSGI_TEMPLATE = '''"""WSGI file for BASSIGNANA EPC CONTROL.

Written by deploy/pythonanywhere_deploy.py. Edit ACCESS_PASSWORD here (and
press Reload on the Web tab) to change the shared password for the site.
"""
import os
import sys

PROJECT_DIR = {project_dir!r}

# The shared password every employee types once per device.
ACCESS_PASSWORD = {password!r}

os.environ["BASSIGNANA_ACCESS_PASSWORD"] = ACCESS_PASSWORD
# PythonAnywhere terminates HTTPS in front of the application.
os.environ["BASSIGNANA_BEHIND_PROXY"] = "1"
os.environ["BASSIGNANA_HTTPS"] = "1"
# PythonAnywhere keeps files on a network file system, where SQLite's WAL mode
# cannot be used. DELETE is the classic rollback journal and is safe there.
os.environ["BASSIGNANA_SQLITE_JOURNAL_MODE"] = "DELETE"

if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from app import create_app  # noqa: E402

application = create_app()
'''


class DeployError(RuntimeError):
    pass


# --------------------------------------------------------------------------
# API plumbing
# --------------------------------------------------------------------------
class Api:
    """The subset of the PythonAnywhere API this deployment needs."""

    def __init__(self, base, username, token, dry_run=False, log=print):
        self.base = base.rstrip("/")
        self.username = username
        self.token = token
        self.dry_run = dry_run
        self.log = log
        self.calls = []

    def url(self, path):
        return f"{self.base}/api/v0/user/{self.username}/{path.lstrip('/')}"

    def request(self, method, path, data=None, files=None, expect=(200, 201)):
        url = self.url(path)
        self.calls.append((method, path))
        if self.dry_run and method != "GET":
            self.log(f"    [dry run] {method} {path}")
            return 200, {}

        body, content_type = None, None
        if files is not None:
            body, content_type = _multipart(files)
        elif data is not None:
            body = urllib.parse.urlencode(data, doseq=True).encode()
            content_type = "application/x-www-form-urlencoded"

        request = urllib.request.Request(url, data=body, method=method)
        request.add_header("Authorization", f"Token {self.token}")
        if content_type:
            request.add_header("Content-Type", content_type)

        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                return response.status, _decode(response.read())
        except urllib.error.HTTPError as error:
            payload = _decode(error.read())
            if error.code in expect:
                return error.code, payload
            raise DeployError(_explain(error.code, payload, method, path)) from None
        except urllib.error.URLError as error:
            raise DeployError(f"Could not reach {url}: {error.reason}") from None


def _decode(raw):
    text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
    try:
        return json.loads(text)
    except ValueError:
        return {"raw": text}


def _multipart(files):
    """Encode one file upload the way the files API expects."""
    boundary = "----bassignana" + hashlib.sha1(str(time.time()).encode()).hexdigest()[:16]
    buffer = io.BytesIO()
    for name, (filename, payload) in files.items():
        buffer.write(f"--{boundary}\r\n".encode())
        buffer.write(
            f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
            "Content-Type: application/octet-stream\r\n\r\n".encode())
        buffer.write(payload)
        buffer.write(b"\r\n")
    buffer.write(f"--{boundary}--\r\n".encode())
    return buffer.getvalue(), f"multipart/form-data; boundary={boundary}"


def _explain(code, payload, method, path):
    detail = payload.get("detail") or payload.get("error") or payload.get("raw") or payload
    if code == 401:
        return ("The API token was rejected (401). Copy it again from the Account page, "
                "API token tab. A token is tied to one installation: use --host eu if you "
                "registered on eu.pythonanywhere.com.")
    if code == 403:
        return (f"PythonAnywhere refused this call (403): {detail}\n"
                "If it says the API is not available, the account's plan does not include "
                "API access and the Web tab has to be filled in by hand -- deploy/HOSTING.md "
                "section 3 lists every field.")
    if code == 404:
        return (f"{method} {path} was not found (404): {detail}\n"
                "Check that --username is exactly the PythonAnywhere username.")
    return f"{method} {path} failed with HTTP {code}: {detail}"


# --------------------------------------------------------------------------
# Deployment steps
# --------------------------------------------------------------------------
def check_checkout(api, project_dir, log):
    """The repository has to be on the server already (step 2 of HOSTING.md)."""
    status, payload = api.request("GET", f"files/path{project_dir}/app/__init__.py",
                                  expect=(200, 404))
    if status == 404:
        raise DeployError(
            f"{project_dir} does not contain the application yet.\n"
            "Open Consoles -> Bash on pythonanywhere.com and paste this one line first:\n\n"
            "  bash <(curl -fsSL https://raw.githubusercontent.com/bumincetin/bassig/"
            "main/deploy/pythonanywhere_setup.sh)\n\n"
            "It clones the repository and installs the requirements into a virtualenv. "
            "The API cannot do it: it can create a console but only a browser can start one.")
    log(f"    checkout found at {project_dir}")


def check_virtualenv(api, virtualenv, log):
    status, _ = api.request("GET", f"files/path{virtualenv}/bin/python", expect=(200, 404))
    if status == 404:
        log(f"    WARNING: no virtualenv at {virtualenv}. The site will use the system "
            "Python, which may not have Flask-SQLAlchemy. Run the setup script in a "
            "Bash console, then run this again.")
        return False
    log(f"    virtualenv found at {virtualenv}")
    return True


def ensure_webapp(api, domain, python_version, log):
    status, payload = api.request("GET", f"webapps/{domain}/", expect=(200, 404))
    if status == 200:
        log(f"    web app {domain} already exists, updating it")
        return False
    log(f"    creating web app {domain} on Python {python_version}")
    api.request("POST", "webapps/",
                data={"domain_name": domain, "python_version": python_version})
    return True


def configure_webapp(api, domain, project_dir, virtualenv, has_virtualenv, log):
    fields = {
        "source_directory": project_dir,
        "working_directory": project_dir,
        "force_https": "true",
    }
    if has_virtualenv:
        fields["virtualenv_path"] = virtualenv
    api.request("PATCH", f"webapps/{domain}/", data=fields)
    log("    source directory, virtualenv and Force HTTPS set")


def write_wsgi(api, domain, project_dir, password, log):
    content = WSGI_TEMPLATE.format(project_dir=project_dir, password=password)
    path = f"/var/www/{domain.replace('.', '_').replace('-', '_')}_wsgi.py"
    api.request("POST", f"files/path{path}",
                files={"content": ("wsgi.py", content.encode("utf-8"))})
    log(f"    WSGI file written to {path}")
    return path


def set_static_files(api, domain, project_dir, log):
    status, existing = api.request("GET", f"webapps/{domain}/static_files/", expect=(200, 404))
    already = {row.get("url") for row in existing} if isinstance(existing, list) else set()
    for url_prefix, relative in STATIC_MAPPINGS:
        if url_prefix in already:
            continue
        api.request("POST", f"webapps/{domain}/static_files/",
                    data={"url": url_prefix, "path": f"{project_dir}/{relative}"})
    log(f"    {len(STATIC_MAPPINGS)} static mappings in place "
        "(/static/uploads/ deliberately not mapped, so photographs stay behind the password)")


def upload_database(api, project_dir, database, log):
    payload = Path(database).read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    target = f"{project_dir}/data/bassignana.db"

    status, _ = api.request("GET", f"files/path{target}", expect=(200, 404))
    if status == 200:
        raise DeployError(
            f"{target} already exists on the server and would be overwritten.\n"
            "That file is the live project record. If you are sure the server copy is the "
            "empty first-run database, delete it from the Files tab and run this again; if "
            "it already holds site entries, do not upload over it.")

    api.request("POST", f"files/path{target}",
                files={"content": ("bassignana.db", payload)})
    log(f"    uploaded {len(payload) / 1024:.0f} kB to {target}")

    if not api.dry_run:
        status, _ = api.request("GET", f"files/path{target}", expect=(200, 404))
        if status != 200:
            raise DeployError("The database upload could not be read back.")
    log(f"    sha256 {digest[:16]}...")
    return digest


def reload_webapp(api, domain, log):
    api.request("POST", f"webapps/{domain}/reload/")
    log("    reload requested")


def verify(domain, log, attempts=10, delay=6, opener=None):
    """Ask the running site for /healthz, and confirm the gate is closed."""
    open_url = opener or (lambda url: urllib.request.urlopen(url, timeout=20))
    health_url = f"https://{domain}/healthz"
    for attempt in range(1, attempts + 1):
        try:
            with open_url(health_url) as response:
                payload = _decode(response.read())
            if payload.get("status") == "ok":
                log(f"    /healthz -> ok, version {payload.get('version')}, "
                    f"schema {payload.get('schema_version')}, counts {payload.get('counts')}")
                return payload
            raise DeployError(f"/healthz answered {payload}")
        except DeployError:
            raise
        except Exception as error:  # noqa: BLE001 - any transport error is a retry
            if attempt == attempts:
                raise DeployError(
                    f"{health_url} did not answer after {attempts} tries: {error}\n"
                    "Open the Web tab and read the error log; a missing package in the "
                    "virtualenv is the usual cause.") from None
            log(f"    waiting for the site to come up ({attempt}/{attempts})")
            time.sleep(delay)
    return None


def check_gate(domain, log, opener=None):
    """The dashboard must redirect to the login screen, not serve the project."""
    open_url = opener or (lambda url: urllib.request.urlopen(url, timeout=20))

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None

    if opener is None:
        no_redirect = urllib.request.build_opener(_NoRedirect())
        open_url = lambda url: no_redirect.open(url, timeout=20)  # noqa: E731
    try:
        with open_url(f"https://{domain}/") as response:
            status, location = response.status, response.headers.get("Location", "")
    except urllib.error.HTTPError as error:
        status, location = error.code, error.headers.get("Location", "")
    if status in (301, 302) and "/login" in location:
        log("    the dashboard redirects to the login screen: the password gate is on")
        return True
    log(f"    WARNING: / answered {status} instead of redirecting to /login. "
        "The site may be readable without the password -- check ACCESS_PASSWORD in the "
        "WSGI file and reload.")
    return False


# --------------------------------------------------------------------------
def deploy(args, log=print):
    if not args.password and not args.allow_no_password:
        raise DeployError(
            "--password is required: a site on the internet without the shared password "
            "would let anyone who finds the address read and change the project record. "
            "Pass --allow-no-password only for a deliberately public demonstration.")
    if args.database and not Path(args.database).is_file():
        raise DeployError(f"--database {args.database} does not exist.")

    base = args.api_base or API_HOSTS[args.host]
    domain = args.domain or f"{args.username}.pythonanywhere.com"
    project_dir = args.project_dir.rstrip("/") or f"/home/{args.username}/bassignana"
    virtualenv = args.virtualenv.rstrip("/") or f"{project_dir}/venv"

    api = Api(base, args.username, args.token, dry_run=args.dry_run, log=log)

    log(f"Deploying to https://{domain}{'  [dry run]' if args.dry_run else ''}")
    log("  1. checking the checkout")
    check_checkout(api, project_dir, log)
    has_virtualenv = check_virtualenv(api, virtualenv, log)
    log("  2. web app")
    created = ensure_webapp(api, domain, args.python_version, log)
    log("  3. configuration")
    configure_webapp(api, domain, project_dir, virtualenv, has_virtualenv, log)
    write_wsgi(api, domain, project_dir, args.password, log)
    set_static_files(api, domain, project_dir, log)
    if args.database:
        log("  4. live database")
        upload_database(api, project_dir, args.database, log)
    else:
        log("  4. live database: not uploaded (--database was not given). The site starts "
            "with an empty project record; see deploy/HOSTING.md section 6.")
    log("  5. reload")
    reload_webapp(api, domain, log)

    if args.dry_run:
        log("\nDry run finished. No change was made.")
        return 0
    if args.no_verify:
        log(f"\nDone: https://{domain}/")
        return 0

    log("  6. verifying")
    verify(domain, log)
    check_gate(domain, log)
    log(f"\nLive: https://{domain}/")
    log("Everyone signs in with the shared password. Extend the account's "
        '"Run until" date every three months on the Web tab.')
    if created:
        log("Remember to upload static evidence folders if you are migrating an existing "
            "installation: deploy/HOSTING.md section 6.")
    return 0


def build_parser():
    parser = argparse.ArgumentParser(
        description="Deploy BASSIGNANA EPC CONTROL to PythonAnywhere over their API.")
    parser.add_argument("--username", required=True, help="PythonAnywhere username.")
    parser.add_argument("--token", default=os.environ.get("PYTHONANYWHERE_API_TOKEN"),
                        help="API token (Account -> API token). "
                             "Defaults to $PYTHONANYWHERE_API_TOKEN.")
    parser.add_argument("--password", default=os.environ.get("BASSIGNANA_ACCESS_PASSWORD", ""),
                        help="Shared access password for the site.")
    parser.add_argument("--allow-no-password", action="store_true",
                        help="Publish with no password. Almost never right.")
    parser.add_argument("--database", help="Local bassignana.db to upload as the live record.")
    parser.add_argument("--host", choices=sorted(API_HOSTS), default="www",
                        help="'eu' if you registered on eu.pythonanywhere.com.")
    parser.add_argument("--domain", help="Defaults to <username>.pythonanywhere.com.")
    parser.add_argument("--project-dir", default="",
                        help="Checkout on the server. Default /home/<username>/bassignana.")
    parser.add_argument("--virtualenv", default="",
                        help="Virtualenv on the server. Default <project-dir>/venv.")
    parser.add_argument("--python-version", default="3.10",
                        help="Python version for the web app (default 3.10).")
    parser.add_argument("--api-base", help=argparse.SUPPRESS)  # tests point this at a stub
    parser.add_argument("--dry-run", action="store_true",
                        help="Say what would happen without changing anything.")
    parser.add_argument("--no-verify", action="store_true",
                        help="Skip the /healthz check at the end.")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if not args.token:
        print("No API token. Pass --token or set PYTHONANYWHERE_API_TOKEN.", file=sys.stderr)
        return 2
    try:
        return deploy(args)
    except DeployError as error:
        print(f"\nDeployment stopped: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
