"""WebSocket live streaming endpoint (/api/v1/ws/live)."""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import text

from app.core.clock import IST, now
from app.db.engine import get_sessionmaker

router = APIRouter(tags=["websocket"])
logger = logging.getLogger("prajna.api.ws")


class ConnectionManager:
    def __init__(self) -> None:
        self.active_connections: list[WebSocket] = []
        self.subscriptions: dict[WebSocket, set[str]] = {}

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.append(websocket)
        self.subscriptions[websocket] = {"NSE_INDEX|Nifty 50", "NSE_INDEX|Nifty Bank"}

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        self.subscriptions.pop(websocket, None)

    def subscribe(self, websocket: WebSocket, keys: list[str]) -> None:
        if websocket in self.subscriptions:
            self.subscriptions[websocket].update(keys)

    def unsubscribe(self, websocket: WebSocket, keys: list[str]) -> None:
        if websocket in self.subscriptions:
            self.subscriptions[websocket].difference_update(keys)


manager = ConnectionManager()


@router.websocket("/ws/live")
async def websocket_live_endpoint(websocket: WebSocket) -> None:
    await manager.connect(websocket)
    # Send connection greeting
    await websocket.send_json(
        {
            "type": "connected",
            "message": "Connected to Prajna Market Data Stream",
            "server_time": now().isoformat(),
            "subscribed": list(manager.subscriptions.get(websocket, set())),
        }
    )

    async def sender_loop() -> None:
        """Periodically broadcast latest ticks/bars for subscribed keys."""
        try:
            while True:
                await asyncio.sleep(2.0)  # Stream cadence
                sub_keys = manager.subscriptions.get(websocket, set())
                if not sub_keys:
                    continue

                async with get_sessionmaker()() as session:
                    # Fetch latest bar for each subscribed key
                    sql = """
                        select distinct on (instrument_key)
                            instrument_key,
                            timeframe,
                            bar_start_utc,
                            open,
                            high,
                            low,
                            close,
                            volume,
                            knowable_at
                        from ohlcv_bar
                        where instrument_key = any(:keys)
                        order by instrument_key, bar_start_utc desc
                    """
                    rows = (await session.execute(text(sql), {"keys": list(sub_keys)})).all()

                    for r in rows:
                        now_u = now()
                        knowable_at = r[8]
                        st = r[2]
                        st_ist = st.astimezone(IST).strftime("%Y-%m-%d %H:%M:%S IST")
                        age_sec = (now_u - knowable_at).total_seconds() if knowable_at else 0.0

                        msg = {
                            "type": "tick",
                            "instrument_key": r[0],
                            "timeframe": r[1],
                            "bar_start_utc": st.isoformat(),
                            "bar_start_ist": st_ist,
                            "open": float(r[3]),
                            "high": float(r[4]),
                            "low": float(r[5]),
                            "close": float(r[6]),
                            "volume": float(r[7]),
                            "knowable_at": knowable_at.isoformat() if knowable_at else None,
                            "stale": age_sec > 180.0,
                            "age_seconds": round(age_sec, 1),
                        }
                        await websocket.send_json(msg)

                    # Send heartbeat ping
                    await websocket.send_json({"type": "ping", "ts": now_u.isoformat()})

        except (WebSocketDisconnect, asyncio.CancelledError):
            pass
        except Exception as e:
            logger.debug(f"Sender loop error: {e}")

    task = asyncio.create_task(sender_loop())

    try:
        while True:
            data = await websocket.receive_text()
            try:
                payload = json.loads(data)
                action = payload.get("action") or payload.get("type")
                if action == "subscribe":
                    keys = payload.get("keys", [])
                    manager.subscribe(websocket, keys)
                    await websocket.send_json(
                        {
                            "type": "subscribed",
                            "keys": keys,
                            "current_subscriptions": list(manager.subscriptions[websocket]),
                        }
                    )
                elif action == "unsubscribe":
                    keys = payload.get("keys", [])
                    manager.unsubscribe(websocket, keys)
                elif action == "pong":
                    pass
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        task.cancel()
    except Exception:
        manager.disconnect(websocket)
        task.cancel()
