"""The PythonAnywhere deployer, driven against a stub of their API.

The real API cannot be exercised from the test suite, so this stands a small
HTTP server in front of the script that answers the way PythonAnywhere does.
What is proved here is the part that would otherwise only be proved in
production: that the deployer creates the web app once, writes a WSGI file
carrying the access password and the DELETE journal mode, maps the three
static prefixes but never /static/uploads/, refuses to overwrite a live
database, and stops with a readable message when the token is wrong.
"""
from __future__ import annotations

import http.server
import importlib.util
import json
import threading
import urllib.error
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

spec = importlib.util.spec_from_file_location(
    "pa_deploy", ROOT / "deploy" / "pythonanywhere_deploy.py")
pa = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pa)

USERNAME = "bassignana"
TOKEN = "test-token"
PROJECT = f"/home/{USERNAME}/bassignana"


class Stub(http.server.BaseHTTPRequestHandler):
    """Enough of the PythonAnywhere API to drive the deployer."""

    state: dict = {}

    def log_message(self, *args):
        pass

    # -- helpers ----------------------------------------------------------
    def _auth_ok(self):
        return self.headers.get("Authorization") == f"Token {TOKEN}"

    def _send(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length) if length else b""

    def _path(self):
        return self.path.replace(f"/api/v0/user/{USERNAME}/", "", 1)

    @staticmethod
    def _uploaded_content(body):
        """The payload of a single-part multipart upload, as the API stores it."""
        start = body.find(b"\r\n\r\n")
        if start == -1:
            return body
        rest = body[start + 4:]
        end = rest.rfind(b"\r\n--")
        return rest[:end] if end != -1 else rest

    def _record(self, method):
        self.state.setdefault("calls", []).append((method, self._path()))

    # -- verbs ------------------------------------------------------------
    def do_GET(self):
        self._record("GET")
        if not self._auth_ok():
            return self._send(401, {"detail": "Invalid token."})
        path = self._path()
        if path.startswith("files/path"):
            target = path[len("files/path"):]
            if target in self.state["files"]:
                return self._send(200, {"ok": True})
            return self._send(404, {"detail": "not found"})
        if path.startswith("webapps/") and path.endswith("/static_files/"):
            return self._send(200, self.state["static"])
        if path == "webapps/":
            return self._send(200, [self.state["webapp"]] if self.state.get("webapp") else [])
        if path.startswith("webapps/"):
            # PythonAnywhere answers 403, not 404, for a web app that does not
            # exist. The deployer must never depend on this call.
            if self.state.get("webapp"):
                return self._send(200, self.state["webapp"])
            return self._send(403, {"detail": "You do not have permission to perform this action."})
        return self._send(404, {"detail": "unknown"})

    def do_POST(self):
        self._record("POST")
        body = self._body()
        if not self._auth_ok():
            return self._send(401, {"detail": "Invalid token."})
        path = self._path()
        if path.startswith("files/path"):
            target = path[len("files/path"):]
            self.state["files"][target] = self._uploaded_content(body)
            return self._send(200, {"ok": True})
        if path == "webapps/":
            from urllib.parse import unquote_plus
            fields = dict(pair.split("=", 1) for pair in body.decode().split("&"))
            version = unquote_plus(fields.get("python_version", ""))
            # The real API rejects the dotted form outright.
            if "." in version:
                return self._send(400, {"status": "ERROR",
                                        "error_type": "invalid_python_version",
                                        "error_message": f"No such Python version: {version}"})
            self.state["created_with"] = version
            self.state["webapp"] = {"domain_name": f"{USERNAME}.pythonanywhere.com"}
            return self._send(201, self.state["webapp"])
        if path.endswith("/static_files/"):
            fields = dict(pair.split("=", 1) for pair in body.decode().split("&"))
            self.state["static"].append(
                {k: __import__("urllib.parse", fromlist=["unquote"]).unquote_plus(v)
                 for k, v in fields.items()})
            return self._send(201, {"ok": True})
        if path.endswith("/reload/"):
            self.state["reloaded"] = self.state.get("reloaded", 0) + 1
            return self._send(200, {"status": "OK"})
        return self._send(404, {"detail": "unknown"})

    def do_PATCH(self):
        self._record("PATCH")
        body = self._body()
        if not self._auth_ok():
            return self._send(401, {"detail": "Invalid token."})
        from urllib.parse import unquote_plus
        fields = dict(pair.split("=", 1) for pair in body.decode().split("&"))
        self.state["patched"] = {k: unquote_plus(v) for k, v in fields.items()}
        return self._send(200, {"ok": True})


@pytest.fixture()
def stub():
    Stub.state = {"files": {}, "static": [], "webapp": None, "calls": []}
    server = http.server.HTTPServer(("127.0.0.1", 0), Stub)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield Stub.state, f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()


def checkout_present(state):
    """Pretend the setup script has already run on the server."""
    state["files"][f"{PROJECT}/app/__init__.py"] = b"x"
    state["files"][f"{PROJECT}/venv/bin/python"] = b"x"


def run(base, extra=(), token=TOKEN):
    lines = []
    argv = ["--username", USERNAME, "--token", token, "--password", "shared-secret",
            "--api-base", base, "--no-verify", *extra]
    args = pa.build_parser().parse_args(argv)
    code = pa.deploy(args, log=lines.append)
    return code, "\n".join(lines)


class TestAFreshDeployment:
    def test_it_creates_configures_and_reloads(self, stub):
        state, base = stub
        checkout_present(state)
        code, output = run(base)
        assert code == 0
        assert state["webapp"] is not None
        assert state["reloaded"] == 1
        assert state["patched"]["source_directory"] == PROJECT
        assert state["patched"]["virtualenv_path"] == f"{PROJECT}/venv"
        assert state["patched"]["force_https"] == "true"

    def test_the_wsgi_file_carries_the_password_and_the_journal_mode(self, stub):
        state, base = stub
        checkout_present(state)
        run(base)
        wsgi = state["files"]["/var/www/bassignana_pythonanywhere_com_wsgi.py"].decode()
        assert "shared-secret" in wsgi
        assert 'BASSIGNANA_SQLITE_JOURNAL_MODE"] = "DELETE"' in wsgi
        assert 'BASSIGNANA_HTTPS"] = "1"' in wsgi
        assert 'BASSIGNANA_BEHIND_PROXY"] = "1"' in wsgi
        assert PROJECT in wsgi
        assert "create_app()" in wsgi

    def test_uploads_are_never_served_by_the_static_file_server(self, stub):
        state, base = stub
        checkout_present(state)
        run(base)
        mapped = {row["url"] for row in state["static"]}
        assert mapped == {"/static/vendor/", "/static/css/", "/static/js/"}
        assert not any(row["url"].rstrip("/") in ("/static", "/static/uploads")
                       for row in state["static"])

    def test_running_it_twice_does_not_duplicate_anything(self, stub):
        state, base = stub
        checkout_present(state)
        run(base)
        run(base)
        assert len(state["static"]) == 3
        assert state["reloaded"] == 2
        assert sum(1 for method, path in state["calls"]
                   if method == "POST" and path == "webapps/") == 1


class TestThePythonVersionFormat:
    """PythonAnywhere wants python313, not 3.13.

    Sending the dotted form is answered with "No such Python version: 3.13",
    which reads as though the interpreter were missing rather than as a format
    error, and cost a deployment its first attempt.
    """

    @pytest.mark.parametrize("given", ["3.13", "python313", "3.13 ", "Python3.13", "313"])
    def test_every_spelling_becomes_the_one_the_api_accepts(self, given):
        assert pa.normalise_python_version(given) == "python313"

    @pytest.mark.parametrize("given", ["", "three", "3.x", "python"])
    def test_nonsense_is_rejected_with_an_explanation(self, given):
        with pytest.raises(pa.DeployError, match="not a version number"):
            pa.normalise_python_version(given)

    def test_the_create_call_sends_the_undotted_form(self, stub):
        state, base = stub
        checkout_present(state)
        run(base, extra=["--python-version", "3.13"])
        assert state["created_with"] == "python313"


class TestItRefusesToDoHarm:
    def test_a_missing_checkout_stops_with_the_console_instruction(self, stub):
        state, base = stub
        with pytest.raises(pa.DeployError) as error:
            run(base)
        assert "Consoles -> Bash" in str(error.value)
        assert state["webapp"] is None

    def test_no_password_is_refused(self, stub):
        state, base = stub
        checkout_present(state)
        args = pa.build_parser().parse_args(
            ["--username", USERNAME, "--token", TOKEN, "--password", "",
             "--api-base", base, "--no-verify"])
        with pytest.raises(pa.DeployError, match="--password is required"):
            pa.deploy(args, log=lambda *a: None)

    def test_a_deliberate_public_deployment_is_still_possible(self, stub):
        state, base = stub
        checkout_present(state)
        code, _ = run(base, extra=["--allow-no-password"] , token=TOKEN)
        assert code == 0

    def test_an_existing_database_is_never_overwritten(self, stub, tmp_path):
        state, base = stub
        checkout_present(state)
        state["files"][f"{PROJECT}/data/bassignana.db"] = b"live record"
        local = tmp_path / "bassignana.db"
        local.write_bytes(b"my local copy")
        with pytest.raises(pa.DeployError, match="already exists on the server"):
            run(base, extra=["--database", str(local)])
        assert state["files"][f"{PROJECT}/data/bassignana.db"] == b"live record"

    def test_the_database_is_uploaded_when_the_server_has_none(self, stub, tmp_path):
        state, base = stub
        checkout_present(state)
        local = tmp_path / "bassignana.db"
        local.write_bytes(b"SQLite format 3\x00 pretend")
        code, output = run(base, extra=["--database", str(local)])
        assert code == 0
        assert state["files"][f"{PROJECT}/data/bassignana.db"] == local.read_bytes()

    def test_a_missing_local_database_is_caught_before_anything_is_touched(self, stub):
        state, base = stub
        checkout_present(state)
        with pytest.raises(pa.DeployError, match="does not exist"):
            run(base, extra=["--database", "nowhere/bassignana.db"])
        assert state["webapp"] is None

    def test_a_bad_token_is_explained(self, stub):
        state, base = stub
        checkout_present(state)
        with pytest.raises(pa.DeployError) as error:
            run(base, token="wrong")
        assert "401" in str(error.value) and "API token" in str(error.value)

    def test_a_dry_run_changes_nothing(self, stub):
        state, base = stub
        checkout_present(state)
        code, output = run(base, extra=["--dry-run"])
        assert code == 0
        assert state["webapp"] is None
        assert state["static"] == []
        assert "reloaded" not in state
        assert "dry run" in output.lower()


class TestTheGeneratedWsgiFileActuallyWorks:
    """The WSGI file is what PythonAnywhere imports; a typo in it is a dead site.

    So the file the deployer produced is executed for real, in a subprocess
    with its own scratch data directory, and the application it builds is
    asked to serve a page.
    """

    def test_it_boots_an_application_that_serves_and_gates(self, stub, tmp_path):
        import subprocess
        import sys

        state, base = stub
        checkout_present(state)
        run(base)
        wsgi = state["files"]["/var/www/bassignana_pythonanywhere_com_wsgi.py"].decode()
        # The server-side checkout path is this repository, for the test.
        wsgi = wsgi.replace(f"PROJECT_DIR = {PROJECT!r}", f"PROJECT_DIR = {str(ROOT)!r}")
        script = tmp_path / "pa_wsgi.py"
        script.write_text(wsgi + '''
import json
client = application.test_client()
health = client.get("/healthz")
root = client.get("/")
login = client.get("/login?lang=it")
print(json.dumps({
    "health": health.status_code,
    "status": health.get_json().get("status"),
    "root": root.status_code,
    "location": root.headers.get("Location", ""),
    "login_it": login.status_code,
    "journal": os.environ["BASSIGNANA_SQLITE_JOURNAL_MODE"],
}))
''', encoding="utf-8")

        environment = {k: v for k, v in __import__("os").environ.items()
                       if not k.startswith("BASSIGNANA_")}
        environment["BASSIGNANA_DATA_DIR"] = str(tmp_path / "live")
        result = subprocess.run([sys.executable, str(script)], cwd=ROOT, env=environment,
                                capture_output=True, text=True)
        assert result.returncode == 0, result.stderr[-2000:]
        payload = json.loads(result.stdout.strip().splitlines()[-1])
        assert payload["health"] == 200 and payload["status"] == "ok"
        # The shared password baked into the file must actually gate the site.
        assert payload["root"] == 302 and "/login" in payload["location"]
        assert payload["login_it"] == 200
        assert payload["journal"] == "DELETE"
        # And the live database really was created where the WSGI file said.
        assert (tmp_path / "live" / "bassignana.db").is_file()


class TestVerification:
    def test_a_healthy_site_is_accepted(self):
        class Response:
            status = 200

            def read(self):
                return json.dumps({"status": "ok", "version": "1.2.0",
                                   "schema_version": 2, "counts": {}}).encode()

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        payload = pa.verify("example.test", log=lambda *a: None,
                            opener=lambda url: Response())
        assert payload["status"] == "ok"

    def test_a_site_that_never_answers_is_reported(self):
        def broken(url):
            raise urllib.error.URLError("refused")

        with pytest.raises(pa.DeployError, match="did not answer"):
            pa.verify("example.test", log=lambda *a: None, opener=broken,
                      attempts=2, delay=0)

    def test_the_closed_gate_is_recognised(self):
        class Redirect:
            status = 302
            headers = {"Location": "https://example.test/login?next=/"}

            def read(self):
                return b""

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        assert pa.check_gate("example.test", log=lambda *a: None,
                             opener=lambda url: Redirect()) is True

    def test_an_open_site_is_warned_about(self):
        class Ok:
            status = 200
            headers = {}

            def read(self):
                return b"<html>the dashboard</html>"

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        messages = []
        assert pa.check_gate("example.test", log=messages.append,
                             opener=lambda url: Ok()) is False
        assert any("WARNING" in m for m in messages)
