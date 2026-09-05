#!/usr/bin/env python3
"""BASSIGNANA EPC CONTROL — local launcher.

Bassignana Solar 2 — Project & Site Control System.

Start with:      python run.py
Then open the printed localhost address, or the LAN address from a phone or
tablet on the same Wi-Fi.

The application runs entirely on this machine. It contacts no cloud service,
no API and no external database.

By default it is served by Waitress, a production WSGI server that ships as a
pure-Python wheel and needs no compiler, no configuration file and no internet
connection at runtime. If Waitress is not installed the launcher falls back to
the Flask development server and says so, rather than refusing to start.
"""
from __future__ import annotations

import argparse
import os
import socket
import sys

from app import __version__, create_app


def detect_lan_ip():
    """Best-effort LAN address of this machine, without sending any traffic."""
    candidates = []
    try:
        # Opening a UDP socket does not transmit anything; it only asks the OS
        # which local interface would be used to reach that address.
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.settimeout(0.2)
        probe.connect(("10.255.255.255", 1))
        candidates.append(probe.getsockname()[0])
        probe.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            address = info[4][0]
            if address not in candidates and not address.startswith("127."):
                candidates.append(address)
    except OSError:
        pass
    return [ip for ip in candidates if not ip.startswith("127.")]


def default_port():
    """BASSIGNANA_PORT, else the PORT most hosting platforms inject, else 5000."""
    for name in ("BASSIGNANA_PORT", "PORT"):
        value = (os.environ.get(name) or "").strip()
        if value.isdigit():
            return int(value)
    return 5000


def banner(host, port, app, server="Waitress"):
    lan_ips = detect_lan_ip()
    line = "=" * 72
    print(line)
    print("  BASSIGNANA EPC CONTROL" + f"   v{__version__}")
    print("  Bassignana Solar 2 - Project & Site Control System")
    print(line)
    print(f"  Server   : {server}")
    print(f"  Database : {app.config['SQLALCHEMY_DATABASE_URI']}")
    print(f"  Uploads  : {app.config['UPLOAD_DIR']}")
    print(f"  Backups  : {app.config['BACKUP_DIR']}")
    print(f"  Log file : {app.config.get('LOG_PATH')}")
    if app.config.get("ACCESS_PASSWORD"):
        print("  Access   : shared password required (BASSIGNANA_ACCESS_PASSWORD is set)")
    else:
        print("  Access   : open to everyone who can reach this address (no password set)")
    print(line)
    print(f"  On this computer : http://127.0.0.1:{port}/")
    print(f"                     http://localhost:{port}/")
    if lan_ips:
        print("  On the same Wi-Fi / LAN (phone, tablet, site laptop):")
        for ip in lan_ips:
            print(f"                     http://{ip}:{port}/")
    else:
        print("  LAN address could not be detected. Run 'ipconfig' (Windows) or")
        print("  'ip addr' (Linux) and use this machine's IPv4 address with the port above.")
    print(line)
    print("  No internet connection is required. Press CTRL+C to stop.")
    print(line, flush=True)


def serve(app, host, port, threads, use_dev_server=False):
    """Serve the application, preferring a production WSGI server."""
    if not use_dev_server:
        try:
            from waitress import serve as waitress_serve
        except ImportError:
            print("  NOTE: Waitress is not installed, so the Flask development server is")
            print("        being used instead. It works, but for day-to-day site use run:")
            print("            pip install waitress")
            print("        and start again.", flush=True)
        else:
            banner(host, port, app, server=f"Waitress ({threads} threads)")
            waitress_serve(app, host=host, port=port, threads=threads,
                           ident="Bassignana EPC Control")
            return

    banner(host, port, app, server="Flask development server")
    app.run(host=host, port=port, debug=use_dev_server,
            use_reloader=use_dev_server, threaded=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run BASSIGNANA EPC CONTROL locally.")
    parser.add_argument("--host", default=os.environ.get("BASSIGNANA_HOST", "0.0.0.0"),
                        help="Interface to bind (default 0.0.0.0, reachable on the LAN).")
    parser.add_argument("--port", type=int, default=default_port(),
                        help="Port to listen on (default 5000, or the platform's PORT).")
    parser.add_argument("--threads", type=int,
                        default=int(os.environ.get("BASSIGNANA_THREADS", 8)),
                        help="Worker threads for the production server (default 8).")
    parser.add_argument("--debug", action="store_true",
                        help="Use the Flask development server with the reloader.")
    args = parser.parse_args(argv)

    app = create_app()
    try:
        serve(app, args.host, args.port, args.threads, use_dev_server=args.debug)
    except OSError as exc:
        print(f"\nCould not start on port {args.port}: {exc}")
        print(f"Try another port, for example:  python run.py --port {args.port + 1}")
        return 1
    except KeyboardInterrupt:
        print("\nStopped. Data is saved in data/bassignana.db.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
