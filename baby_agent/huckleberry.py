"""Singleton manager for the HuckleberryAPI client.

Handles authentication, per-child realtime listeners, and an in-memory
state cache so the agent always has fresh baby status.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
import uuid
from datetime import datetime
from typing import Any

from huckleberry_api import HuckleberryAPI  # type: ignore[import]

from .config import settings

log = logging.getLogger(__name__)


class HuckleberryManager:
    """Single shared manager instantiated once at app startup."""

    def __init__(self) -> None:
        self._api: HuckleberryAPI | None = None
        self._authenticated = False
        self._children: list[dict[str, Any]] = []  # [{uid, name, ...}, ...]
        self._state_cache: dict[str, dict[str, Any]] = {}  # child_uid → state
        self._feed_cache: dict[str, dict[str, Any]] = {}   # child_uid → feed
        self._lock = threading.Lock()
        self._listener_stops: list[Any] = []

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def startup(self) -> None:
        """Authenticate and register realtime listeners for all children."""
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._sync_startup)

    def _sync_startup(self) -> None:
        self._api = HuckleberryAPI(
            email=settings.huckleberry_email,
            password=settings.huckleberry_password,
            timezone=settings.huckleberry_timezone,
        )
        self._api.authenticate()
        self._authenticated = True
        log.info("Huckleberry authenticated successfully.")

        self._children = self._api.get_children()
        log.info("Found %d child(ren): %s", len(self._children), [c.get("name") for c in self._children])

        for child in self._children:
            uid = child["uid"]
            self._state_cache[uid] = {}
            self._feed_cache[uid] = {}
            try:
                stop = self._api.setup_realtime_listener(uid, self._make_state_callback(uid))
                self._listener_stops.append(stop)
            except Exception:
                log.warning("Could not register realtime listener for child %s", uid, exc_info=True)
            try:
                stop = self._api.setup_feed_listener(uid, self._make_feed_callback(uid))
                self._listener_stops.append(stop)
            except Exception:
                log.warning("Could not register feed listener for child %s", uid, exc_info=True)

    async def teardown(self) -> None:
        """Stop all Firebase listeners."""
        for stop_fn in self._listener_stops:
            try:
                if asyncio.iscoroutinefunction(stop_fn):
                    await stop_fn()
                else:
                    stop_fn()
            except Exception:
                pass
        self._listener_stops.clear()
        log.info("Huckleberry listeners stopped.")

    # ------------------------------------------------------------------
    # Realtime callbacks
    # ------------------------------------------------------------------

    def _make_state_callback(self, uid: str):
        def callback(data: dict[str, Any]) -> None:
            with self._lock:
                self._state_cache[uid] = data or {}
            log.debug("State cache updated for child %s", uid)
        return callback

    def _make_feed_callback(self, uid: str):
        def callback(data: dict[str, Any]) -> None:
            with self._lock:
                self._feed_cache[uid] = data or {}
            log.debug("Feed cache updated for child %s", uid)
        return callback

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @property
    def authenticated(self) -> bool:
        return self._authenticated

    @property
    def children(self) -> list[dict[str, Any]]:
        return self._children

    def get_primary_child_uid(self) -> str | None:
        if not self._children:
            return None
        return self._children[0]["uid"]

    def get_child_name(self, uid: str) -> str:
        for c in self._children:
            if c["uid"] == uid:
                return c.get("name", uid)
        return uid

    def summarize_current_state(self, uid: str) -> str:
        """Return a brief human-readable state string for the system prompt."""
        with self._lock:
            state = self._state_cache.get(uid, {})
            feed = self._feed_cache.get(uid, {})

        if not state and not feed:
            return "State not yet available (Firebase loading…)"

        lines: list[str] = []

        # Sleep
        sleep = state.get("sleep") or state.get("currentSleep")
        if sleep:
            status = sleep.get("status", "unknown")
            start = sleep.get("startTime") or sleep.get("start")
            if start:
                try:
                    dt = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
                    time_str = dt.strftime("%-I:%M %p")
                    lines.append(f"Sleep: {status} since {time_str}")
                except Exception:
                    lines.append(f"Sleep: {status}")
            else:
                lines.append(f"Sleep: {status}")
        else:
            lines.append("Sleep: not active")

        # Feeding
        feeding = feed.get("feeding") or state.get("currentFeeding")
        if feeding:
            status = feeding.get("status", "unknown")
            side = feeding.get("side", "")
            side_str = f" ({side})" if side else ""
            lines.append(f"Feeding: {status}{side_str}")
        else:
            lines.append("Feeding: not active")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Action methods — async wrappers around sync Huckleberry API
    # ------------------------------------------------------------------

    async def _run(self, fn, *args, **kwargs):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: fn(*args, **kwargs))

    async def get_current_state(self, child_uid: str) -> dict[str, Any]:
        with self._lock:
            return {
                "state": dict(self._state_cache.get(child_uid, {})),
                "feed": dict(self._feed_cache.get(child_uid, {})),
            }

    async def start_sleep(self, child_uid: str) -> dict[str, Any]:
        return await self._run(self._api.start_sleep, child_uid)

    async def pause_sleep(self, child_uid: str) -> dict[str, Any]:
        return await self._run(self._api.pause_sleep, child_uid)

    async def resume_sleep(self, child_uid: str) -> dict[str, Any]:
        return await self._run(self._api.resume_sleep, child_uid)

    async def complete_sleep(self, child_uid: str) -> dict[str, Any]:
        return await self._run(self._api.complete_sleep, child_uid)

    async def cancel_sleep(self, child_uid: str) -> dict[str, Any]:
        return await self._run(self._api.cancel_sleep, child_uid)

    async def start_feeding(self, child_uid: str, side: str | None = None) -> dict[str, Any]:
        kwargs = {}
        if side:
            kwargs["side"] = side
        return await self._run(self._api.start_feeding, child_uid, **kwargs)

    async def pause_feeding(self, child_uid: str) -> dict[str, Any]:
        return await self._run(self._api.pause_feeding, child_uid)

    async def resume_feeding(self, child_uid: str) -> dict[str, Any]:
        return await self._run(self._api.resume_feeding, child_uid)

    async def switch_feeding_side(self, child_uid: str) -> dict[str, Any]:
        return await self._run(self._api.switch_feeding_side, child_uid)

    async def complete_feeding(self, child_uid: str) -> dict[str, Any]:
        return await self._run(self._api.complete_feeding, child_uid)

    async def cancel_feeding(self, child_uid: str) -> dict[str, Any]:
        return await self._run(self._api.cancel_feeding, child_uid)

    def _sync_log_breastfeeding(
        self,
        child_uid: str,
        left_duration_minutes: float,
        right_duration_minutes: float,
        last_side: str | None,
    ) -> dict[str, Any]:
        left_sec = left_duration_minutes * 60
        right_sec = right_duration_minutes * 60
        total_sec = left_sec + right_sec

        if last_side is None:
            last_side = "right" if right_sec >= left_sec else "left"

        now = time.time()
        start_time = now - total_sec
        interval_id = f"{int(now * 1000)}-{uuid.uuid4().hex[:20]}"
        offset = self._api._get_timezone_offset_minutes()

        client = self._api._get_firestore_client()
        feed_ref = client.collection("feed").document(child_uid)

        feed_ref.collection("intervals").document(interval_id).set({
            "mode": "breast",
            "start": start_time,
            "lastSide": last_side,
            "lastUpdated": now,
            "leftDuration": left_sec,
            "rightDuration": right_sec,
            "offset": offset,
            "end_offset": offset,
        })

        feed_ref.set({
            "prefs": {
                "lastNursing": {
                    "mode": "breast",
                    "start": start_time,
                    "duration": total_sec,
                    "leftDuration": left_sec,
                    "rightDuration": right_sec,
                    "offset": offset,
                },
                "timestamp": {"seconds": now},
                "local_timestamp": now,
            }
        }, merge=True)

        return {
            "status": "ok",
            "left_minutes": left_duration_minutes,
            "right_minutes": right_duration_minutes,
            "last_side": last_side,
        }

    async def log_breastfeeding(
        self,
        child_uid: str,
        left_duration_minutes: float = 0.0,
        right_duration_minutes: float = 0.0,
        last_side: str | None = None,
    ) -> dict[str, Any]:
        return await self._run(
            self._sync_log_breastfeeding,
            child_uid,
            left_duration_minutes=left_duration_minutes,
            right_duration_minutes=right_duration_minutes,
            last_side=last_side,
        )

    async def log_bottle_feeding(
        self,
        child_uid: str,
        amount: float,
        bottle_type: str,
        units: str,
    ) -> dict[str, Any]:
        return await self._run(
            self._api.log_bottle_feeding,
            child_uid,
            amount=amount,
            bottle_type=bottle_type,
            units=units,
        )

    async def log_diaper(
        self,
        child_uid: str,
        mode: str,
        pee_amount: str | None = None,
        poo_amount: str | None = None,
        color: str | None = None,
        consistency: str | None = None,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"mode": mode}
        if pee_amount is not None:
            kwargs["pee_amount"] = pee_amount
        if poo_amount is not None:
            kwargs["poo_amount"] = poo_amount
        if color:
            kwargs["color"] = color
        if consistency:
            kwargs["consistency"] = consistency
        return await self._run(self._api.log_diaper, child_uid, **kwargs)

    async def log_growth(
        self,
        child_uid: str,
        weight: float | None = None,
        height: float | None = None,
        head: float | None = None,
        units: str = "imperial",
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"units": units}
        if weight is not None:
            kwargs["weight"] = weight
        if height is not None:
            kwargs["height"] = height
        if head is not None:
            kwargs["head"] = head
        return await self._run(self._api.log_growth, child_uid, **kwargs)

    async def get_growth_data(self, child_uid: str) -> dict[str, Any]:
        return await self._run(self._api.get_growth_data, child_uid)

    async def get_history(
        self,
        child_uid: str,
        start_timestamp: int,
        end_timestamp: int,
    ) -> dict[str, Any]:
        return await self._run(self._api.get_calendar_events, child_uid, start_timestamp, end_timestamp)


# Module-level singleton (populated in main.py lifespan)
manager = HuckleberryManager()
