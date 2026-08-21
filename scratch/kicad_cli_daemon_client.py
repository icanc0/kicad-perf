#!/usr/bin/env python3
"""
Minimal reference client for the `kicad-cli daemon` wire protocol.

Usage:
    kicad_cli_daemon_client.py [--socket PATH] -- <args to send>

Sends the argv as a request frame to a running daemon, reads the response,
prints captured stdout to stdout, captured stderr to stderr, and exits
with the daemon's returned exit code.

Wire protocol (must match kicad/cli/command_daemon.cpp exactly):

    Request:
        u32 be magic  = 0x4B434C49  ("KCLI")
        u32 be argc
        for each arg:
            u32 be len
            bytes
        u32 be cwd_len
        bytes cwd

    Response:
        u32 be magic      = 0x53544154  ("STAT")
        u32 be exit_code
        u32 be stdout_len
        bytes stdout
        u32 be stderr_len
        bytes stderr

Run this against the daemon started with:

    kicad-cli daemon start

Then in another terminal:

    python3 kicad_cli_daemon_client.py -- --version

Once the daemon dispatcher is wired up (patch 0010), this will replay any
`kicad-cli pcb export …` invocation with the daemon paying startup cost
once instead of per-call.
"""

from __future__ import annotations

import argparse
import os
import socket
import struct
import sys


REQ_MAGIC = 0x4B434C49  # "KCLI"
RESP_MAGIC = 0x53544154  # "STAT"


def default_socket_path() -> str:
    xdg = os.environ.get("XDG_RUNTIME_DIR")
    if xdg:
        return os.path.join(xdg, "kicad-cli.sock")
    return f"/tmp/kicad-cli-{os.getuid()}.sock"


def recv_all(sock: socket.socket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("peer closed early")
        buf.extend(chunk)
    return bytes(buf)


def send_request(sock: socket.socket, argv: list[str], cwd: str) -> None:
    body = bytearray()
    body += struct.pack(">II", REQ_MAGIC, len(argv))
    for arg in argv:
        b = arg.encode("utf-8")
        body += struct.pack(">I", len(b))
        body += b
    cwd_b = cwd.encode("utf-8")
    body += struct.pack(">I", len(cwd_b))
    body += cwd_b
    sock.sendall(bytes(body))


def read_response(sock: socket.socket) -> tuple[int, bytes, bytes]:
    hdr = recv_all(sock, 12)
    magic, exit_code, stdout_len = struct.unpack(">III", hdr)
    if magic != RESP_MAGIC:
        raise ValueError(f"bad response magic: {magic:#x}")
    stdout = recv_all(sock, stdout_len) if stdout_len else b""
    stderr_len = struct.unpack(">I", recv_all(sock, 4))[0]
    stderr = recv_all(sock, stderr_len) if stderr_len else b""
    return exit_code, stdout, stderr


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--socket", default=None)
    ap.add_argument("argv", nargs="*", help="argv to send (place after --)")
    args = ap.parse_args()

    path = args.socket or default_socket_path()

    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.connect(path)
        send_request(sock, args.argv, os.getcwd())
        exit_code, out, err = read_response(sock)

    if out:
        sys.stdout.buffer.write(out)
        sys.stdout.buffer.flush()
    if err:
        sys.stderr.buffer.write(err)
        sys.stderr.buffer.flush()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
