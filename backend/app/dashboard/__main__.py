"""Run the research dashboard: python -m app.dashboard [--host H] [--port P]."""

from __future__ import annotations

import argparse

import uvicorn


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8600)
    a = ap.parse_args()
    uvicorn.run("app.dashboard.server:app", host=a.host, port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
