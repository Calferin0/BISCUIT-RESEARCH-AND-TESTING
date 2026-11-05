"""Background entry point: serve BRT with waitress on every interface.

start-brt.bat runs this under pythonw.exe, so there's no console window. Everything goes to
brt.log in the data dir, because a pythonw crash is otherwise completely silent.
"""
from __future__ import annotations

import logging
import os
import socket
import sys

from waitress import serve

from app import create_app, resolve_data_dir
from app.util import lan_ip


def main() -> int:
    data_dir = resolve_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=data_dir / "brt.log", level=logging.INFO, encoding="utf-8",
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    log = logging.getLogger("brt")
    port = int(os.environ.get("BRT_PORT", "8080"))

    try:
        sock = _listen_exclusive(port)
    except OSError:
        log.error("Port %d is already in use. BRT (or something else) is already running; not starting another.", port)
        print(f"Port {port} is already in use. Is BRT already running?")
        return 1

    try:
        app = create_app()
    except Exception:
        log.exception("BRT failed to start")
        sock.close()
        return 1

    host = app.config.get("PUBLIC_HOST") or lan_ip()
    log.info("BRT up. Agents: http://%s:%d  Admin (this PC): http://127.0.0.1:%d/admin/", host, port, port)
    print(f"BRT up. Agents: http://{host}:{port}   Admin: http://127.0.0.1:{port}/admin/")

    pid_file = data_dir / "brt.pid"  # informational; stop-brt.bat matches on the .venv path instead
    pid_file.write_text(str(os.getpid()))
    try:
        serve(app, sockets=[sock], threads=8)
    finally:
        pid_file.unlink(missing_ok=True)
    return 0


def _listen_exclusive(port: int) -> socket.socket:
    """Bind the port so that a second BRT *fails* instead of silently sharing it.

    By default waitress sets SO_REUSEADDR, which on Windows (unlike Linux) lets several processes
    listen on the same port at once. Requests then land on whichever one Windows picks
    (seen 2026-11-05: three copies running after start-brt.bat was run three times).
    SO_EXCLUSIVEADDRUSE is the Windows opt-out. Other OSes don't have it and don't need it.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    try:
        sock.bind(("0.0.0.0", port))
        sock.listen(128)
    except OSError:
        sock.close()
        raise
    return sock


if __name__ == "__main__":
    sys.exit(main())
