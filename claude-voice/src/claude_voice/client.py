"""Tiny stdlib-only client for the daemon socket (used by hooks and the ctl CLI)."""

import json
import socket

from .config import SOCKET_PATH


class DaemonUnavailable(Exception):
    pass


def request(cmd: str, timeout: float | None = 5.0, **args) -> dict:
    """Send one JSON-line request and return the JSON-line reply."""
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect(str(SOCKET_PATH))
    except OSError as e:
        sock.close()
        raise DaemonUnavailable(str(e)) from e
    with sock:
        sock.sendall((json.dumps({"cmd": cmd, **args}) + "\n").encode())
        buf = b""
        while not buf.endswith(b"\n"):
            chunk = sock.recv(65536)
            if not chunk:
                break
            buf += chunk
    if not buf:
        raise DaemonUnavailable("daemon closed the connection without replying")
    return json.loads(buf)
