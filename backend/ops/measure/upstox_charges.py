"""Actual broker charges for the E2 cost model, from Upstox's own brokerage-details
endpoint (GET /v2/charges/brokerage). READ-ONLY: the REST client is GET-only; no
order, no position, no database write. Every raw response is saved with the request
and the fetch time, so each rate carries its source and date.

  .venv/bin/python ops/measure/upstox_charges.py [--key K] [--price P]

Grid: product D (delivery) and I (intraday) x BUY and SELL x trade values. Output:
var/stage4/costs/charges_<UTC stamp>.json (raw) and a per-side bps summary on stdout.
Charges are the broker's computation at the fetch time; they are not a statement of
the statutory rates (those are recorded separately with their official source).
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as _dt
import json
import pathlib
import sys
from urllib.parse import urlencode

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.vendor.upstox.auth import load_cached  # noqa: E402
from app.vendor.upstox.rest import UpstoxRestClient  # noqa: E402

OUT = ROOT / "var/stage4/costs"
VALUES = (10_000, 25_000, 100_000, 500_000)          # INR per order


def path(key: str, qty: int, product: str, side: str, price: float) -> str:
    return "/v2/charges/brokerage?" + urlencode({
        "instrument_token": key, "quantity": qty, "product": product,
        "transaction_type": side, "price": f"{price:.2f}"})


async def fetch(key: str, price: float) -> list[dict]:
    rec = load_cached()
    if rec is None:
        raise SystemExit("no cached Upstox token (run the daily login first)")
    rest = UpstoxRestClient(rec.access_token)
    out = []
    try:
        for product in ("D", "I"):
            for side in ("BUY", "SELL"):
                for value in VALUES:
                    qty = max(1, round(value / price))
                    p = path(key, qty, product, side, price)
                    row = {"path": p, "product": product, "side": side, "quantity": qty,
                           "price": price, "trade_value": qty * price}
                    try:
                        r = await rest.get(p)
                    except Exception as e:                # recorded, never guessed
                        out.append({**row, "http_status": None, "response": None,
                                    "error": f"{type(e).__name__}: {e}"[:300],
                                    "fetched_at": _dt.datetime.now(_dt.UTC).isoformat()})
                        continue
                    try:
                        body = json.loads(r.data)
                    except ValueError:
                        body = {"raw": r.data.decode("utf-8", "replace")[:2000]}
                    out.append({**row, "http_status": r.status, "response": body,
                                "fetched_at": r.fetched_at.isoformat(),
                                "request_id": r.request_id})
    finally:
        await rest.aclose()
    return out


def summary(rows: list[dict]) -> list[dict]:
    res = []
    for r in rows:
        ch = ((r["response"] or {}).get("data") or {}).get("charges") or {}
        total = ch.get("total")
        res.append({"product": r["product"], "side": r["side"],
                    "trade_value": round(r["trade_value"], 2), "total": total,
                    "bps": round(10_000 * total / r["trade_value"], 3)
                    if isinstance(total, (int, float)) else None,
                    "brokerage": ch.get("brokerage"), "taxes": ch.get("taxes"),
                    "other": ch.get("other_charges"), "http_status": r["http_status"]})
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", default="NSE_EQ|INE002A01018")    # RELIANCE (liquid, EQ)
    ap.add_argument("--price", type=float, required=True, help="a recent close (INR)")
    a = ap.parse_args()
    rows = asyncio.run(fetch(a.key, a.price))
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = _dt.datetime.now(_dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    f = OUT / f"charges_{stamp}.json"
    f.write_text(json.dumps({"endpoint": "GET /v2/charges/brokerage (Upstox)",
                             "key": a.key, "rows": rows}, indent=1, default=str))
    print(json.dumps({"written": str(f.relative_to(ROOT)), "summary": summary(rows)},
                     indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
