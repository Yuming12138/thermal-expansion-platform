from __future__ import annotations

import argparse
import threading
import time
import webbrowser
from collections.abc import Sequence
from urllib.error import URLError
from urllib.request import urlopen

import uvicorn


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tep-web",
        description="Start the local thermal-expansion research platform.",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--log-level", default="info")
    return parser


def _browser_url(host: str, port: int) -> str:
    browser_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    return f"http://{browser_host}:{port}/"


def _open_browser_when_ready(url: str, attempts: int = 80) -> None:
    health_url = url.rstrip("/") + "/api/health"
    for _ in range(attempts):
        try:
            with urlopen(health_url, timeout=0.5) as response:  # noqa: S310 - local URL only
                if response.status == 200:
                    webbrowser.open(url)
                    return
        except (OSError, URLError):
            time.sleep(0.25)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not 1 <= args.port <= 65535:
        raise SystemExit("--port must be between 1 and 65535")
    url = _browser_url(args.host, args.port)
    if not args.no_browser:
        threading.Thread(
            target=_open_browser_when_ready,
            args=(url,),
            daemon=True,
        ).start()
    uvicorn.run(
        "te_platform.api.app:app",
        host=args.host,
        port=args.port,
        log_level=args.log_level,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
