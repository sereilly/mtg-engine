r"""Serve the web app on the LAN over both IPv4 and IPv6.

``uvicorn --host ::`` on Windows listens on IPv6 only (asyncio disables
dual-stack sockets), so this script binds one dual-stack socket by hand and
hands it to uvicorn. Run it, then join from any LAN device via
http://<ipv4>:8010/ or http://[<ipv6>]:8010/.

    .\.venv\Scripts\python.exe scripts/serve_lan.py [--port 8010]
"""

from __future__ import annotations

import argparse
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8010)
    args = parser.parse_args()

    sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    # 0 = accept IPv4 connections on this IPv6 socket too (dual-stack).
    sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
    sock.bind(("::", args.port))

    hostname = socket.gethostname()
    print(f"Serving on all interfaces, port {args.port} (IPv4 + IPv6)")
    print(f"LAN players can also try: http://{hostname}:{args.port}/")

    config = uvicorn.Config("web.app:app", port=args.port)
    uvicorn.Server(config).run(sockets=[sock])


if __name__ == "__main__":
    main()
