"""Blocking client for the porcaria daemon's UDS IPC."""
from __future__ import annotations

import socket
from pathlib import Path
from typing import Any

from porcaria import paths
from porcaria.daemon.rpc import Request, Response


class DaemonNotRunning(RuntimeError):
    pass


class Client:
    def __init__(self, socket_path: Path | None = None, timeout: float = 600.0) -> None:
        self.socket_path = socket_path or paths.ipc_socket()
        self.timeout = timeout

    def is_running(self) -> bool:
        if not self.socket_path.exists():
            return False
        try:
            with self._connect() as s:
                s.sendall((Request(method="ping").to_json() + "\n").encode())
                _ = _readline(s)
                return True
        except OSError:
            return False

    def call(self, method: str, params: dict[str, Any] | None = None) -> Response:
        try:
            with self._connect() as s:
                req = Request(method=method, params=params or {})
                s.sendall((req.to_json() + "\n").encode())
                line = _readline(s)
        except FileNotFoundError as e:
            raise DaemonNotRunning(f"daemon socket not found: {self.socket_path}") from e
        except ConnectionRefusedError as e:
            raise DaemonNotRunning(f"daemon not accepting connections: {e}") from e
        return Response.from_json(line)

    def _connect(self) -> socket.socket:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(self.timeout)
        s.connect(str(self.socket_path))
        return s


def _readline(sock: socket.socket) -> str:
    chunks: list[bytes] = []
    buf = b""
    while b"\n" not in buf:
        chunk = sock.recv(65536)
        if not chunk:
            break
        chunks.append(chunk)
        # Only keep the tail needed to detect the separator.
        buf = chunks[-1]
    data = b"".join(chunks)
    nl = data.find(b"\n")
    return data[:nl].decode() if nl >= 0 else data.decode()
