"""Serve the read API:  .venv/bin/python -m app.readapi [--host 127.0.0.1] [--port 8090]"""

from __future__ import annotations

import argparse

import uvicorn

ap = argparse.ArgumentParser()
ap.add_argument("--host", default="127.0.0.1")
ap.add_argument("--port", type=int, default=8090)
a = ap.parse_args()
uvicorn.run("app.readapi.main:api", host=a.host, port=a.port, log_level="info")
