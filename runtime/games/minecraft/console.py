"""
Console Minecraft via RCON local si activé dans server.properties.
"""
from __future__ import annotations

import os
import socket
import struct

from flask import current_app


def _server_dir():
    return current_app.config["GAME"]["server"]["install_dir"]


def _properties_path():
    return os.path.join(_server_dir(), "server.properties")


def _read_properties():
    data = {}
    path = _properties_path()
    if not os.path.exists(path):
        return data
    with open(path, encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            data[key.strip()] = value.strip()
    return data


def _recv_exact(sock, size):
    chunks = []
    remaining = size
    while remaining > 0:
        chunk = sock.recv(remaining)
        if not chunk:
            raise ConnectionError("rcon_connection_closed")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _recv_packet(sock):
    size_raw = _recv_exact(sock, 4)
    size = struct.unpack("<i", size_raw)[0]
    payload = _recv_exact(sock, size)
    req_id, packet_type = struct.unpack("<ii", payload[:8])
    body = payload[8:-2].decode("utf-8", errors="replace")
    return req_id, packet_type, body


def _send_packet(sock, req_id, packet_type, body):
    body_bytes = body.encode("utf-8")
    payload = struct.pack("<ii", req_id, packet_type) + body_bytes + b"\x00\x00"
    sock.sendall(struct.pack("<i", len(payload)) + payload)


def send_console_command(cmd):
    props = _read_properties()
    if props.get("enable-rcon", "false") != "true":
        return False, "rcon_disabled"

    password = props.get("rcon.password", "")
    if not password:
        return False, "rcon_password_missing"

    try:
        port = int(props.get("rcon.port", "25575"))
    except ValueError:
        return False, "rcon_port_invalid"

    try:
        with socket.create_connection(("127.0.0.1", port), timeout=3) as sock:
            sock.settimeout(3)
            _send_packet(sock, 1, 3, password)
            auth_id, _, _ = _recv_packet(sock)
            if auth_id == -1:
                return False, "rcon_auth_failed"
            _send_packet(sock, 2, 2, cmd)
            _, _, body = _recv_packet(sock)
            return True, body
    except Exception as e:
        return False, str(e)
