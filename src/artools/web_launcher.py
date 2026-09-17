"""Launcher for the local ARTools web interface."""

from __future__ import annotations

import argparse
import socket
import threading
import webbrowser
from collections.abc import Sequence


DEFAULT_HOST = "127.0.0.1"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="artools-gui",
        description="Start the local ARTools web interface.",
    )
    parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help="Server bind address (default: 127.0.0.1).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=0,
        help="Server port. Zero selects a free local port automatically.",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not open the default web browser automatically.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    namespace = build_parser().parse_args(argv)
    if namespace.port < 0 or namespace.port > 65535:
        build_parser().error("--port must be between 0 and 65535")
    port = namespace.port or _free_port(namespace.host)
    url = f"http://{_browser_host(namespace.host)}:{port}/"

    if not namespace.no_browser:
        timer = threading.Timer(0.6, webbrowser.open, args=(url,))
        timer.daemon = True
        timer.start()

    print(f"ARTools web interface: {url}")
    _serve(namespace.host, port)
    return 0


def _serve(host: str, port: int) -> None:
    try:
        import uvicorn
        from .webapp import create_app
    except ImportError as error:
        raise SystemExit(
            "The ARTools web interface requires the 'web' optional dependencies. "
            "Install them with: pip install 'artools[web]'"
        ) from error

    uvicorn.run(create_app(), host=host, port=port, log_level="info")


def _free_port(host: str) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def _browser_host(host: str) -> str:
    return "127.0.0.1" if host in {"0.0.0.0", "::"} else host


__all__ = ["DEFAULT_HOST", "build_parser", "main"]
