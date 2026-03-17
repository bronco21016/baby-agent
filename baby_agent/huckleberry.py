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
from zoneinfo import ZoneInfo
from typing import Any

import aiohttp
from huckleberry_api import HuckleberryAPI  # type: ignore[import]
from huckleberry_api.firebase_types import (  # type: ignore[import]
    FirebaseFeedDocumentData,
    FirebaseSleepDocumentData,
)

from .config import settings

log = logging.getLogger(__name__)


class HuckleberryManager:
    """Single shared manager instantiated once at app startup."""

    def __init__(self) -> None:
        self._api: HuckleberryAPI | None = None
        self._session: aiohttp.ClientSession | None = None
        self._authenticated = False
        self._children: list[dict[str, Any]] = []  # [{uid, name, ...}, ...]
        self._state_cache: dict[str, dict[str, Any]] = {}  # child_uid → state
        self._feed_cache: dict[str, dict[str, Any]] = {}   # child_uid → feed
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def startup(self) -> None:
        """Authenticate and register realtime listeners for all children."""
        self._session = aiohttp.ClientSession()
        self._api = HuckleberryAPI(
            email=settings.huckleberry_email,
            password=settings.huckleberry_password,
            timezone=settings.huckleberry_timezone,
            websession=self._session,
        )
        await self._api.authenticate()
        self._authenticated = True
        log.info("Huckleberry authenticated successfully.")

        user = await self._api.get_user()
        if user is None:
            log.warning("Could not fetch user document; no children available.")
            return

        for ref in user.childList:
            uid = ref.cid
            name = ref.nickname or uid
            try:
                child_doc = await self._api.get_child(uid)
                if child_doc and child_doc.childsName:
                    name = child_doc.childsName
            except Exception:
                log.warning("Could not fetch child document for %s", uid, exc_info=True)
            self._children.append({"uid": uid, "name": name})
            self._state_cache[uid] = {}
            self._feed_cache[uid] = {}

        log.info("Found %d child(ren): %s", len(self._children), [c.get("name") for c in self._children])

        for child in self._children:
            uid = child["uid"]
            try:
                await self._api.setup_sleep_listener(uid, self._make_state_callback(uid))
            except Exception:
                log.warning("Could not register sleep listener for child %s", uid, exc_info=True)
            try:
                await self._api.setup_feed_listener(uid, self._make_feed_callback(uid))
            except Exception:
                log.warning("Could not register feed listener for child %s", uid, exc_info=True)

    async def teardown(self) -> None:
        """Stop all Firebase listeners and close the HTTP session."""
        if self._api is not None:
            try:
                await self._api.stop_all_listeners()
            except Exception:
                pass
        if self._session is not None:
            await self._session.close()
        log.info("Huckleberry listeners stopped.")

    # ------------------------------------------------------------------
    # Realtime callbacks
    # ------------------------------------------------------------------

    def _make_state_callback(self, uid: str):
        def callback(data: FirebaseSleepDocumentData) -> None:
            with self._lock:
                self._state_cache[uid] = data.model_dump() if data else {}
            log.debug("State cache updated for child %s", uid)
        return callback

    def _make_feed_callback(self, uid: str):
        def callback(data: FirebaseFeedDocumentData) -> None:
            with self._lock:
                self._feed_cache[uid] = data.model_dump() if data else {}
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

        # Sleep — new structure: state["timer"] contains active/paused/timerStartTime
        timer = state.get("timer")
        if timer:
            active = timer.get("active", False)
            paused = timer.get("paused", False)
            status = "paused" if paused else ("active" if active else "unknown")
            start_ms = timer.get("timerStartTime")
            if start_ms:
                try:
                    tz = ZoneInfo(settings.huckleberry_timezone)
                    # timerStartTime is milliseconds for sleep
                    dt = datetime.fromtimestamp(start_ms / 1000, tz=tz)
                    time_str = dt.strftime("%-I:%M %p")
                    lines.append(f"Sleep: {status} since {time_str}")
                except Exception:
                    lines.append(f"Sleep: {status}")
            else:
                lines.append(f"Sleep: {status}")
        else:
            lines.append("Sleep: not active")

        # Feeding — new structure: feed["timer"] contains active/paused/activeSide
        feed_timer = feed.get("timer")
        if feed_timer:
            active = feed_timer.get("active", False)
            paused = feed_timer.get("paused", False)
            status = "paused" if paused else ("active" if active else "unknown")
            side = feed_timer.get("activeSide") or feed_timer.get("lastSide", "")
            side_str = f" ({side})" if side and side != "none" else ""
            lines.append(f"Feeding: {status}{side_str}")
        else:
            lines.append("Feeding: not active")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Action methods — async wrappers around the Huckleberry API
    # ------------------------------------------------------------------

    async def get_current_state(self, child_uid: str) -> dict[str, Any]:
        with self._lock:
            return {
                "state": dict(self._state_cache.get(child_uid, {})),
                "feed": dict(self._feed_cache.get(child_uid, {})),
            }

    async def start_sleep(self, child_uid: str) -> dict[str, Any]:
        await self._api.start_sleep(child_uid)
        return {"status": "ok"}

    async def pause_sleep(self, child_uid: str) -> dict[str, Any]:
        await self._api.pause_sleep(child_uid)
        return {"status": "ok"}

    async def resume_sleep(self, child_uid: str) -> dict[str, Any]:
        await self._api.resume_sleep(child_uid)
        return {"status": "ok"}

    async def complete_sleep(self, child_uid: str) -> dict[str, Any]:
        await self._api.complete_sleep(child_uid)
        return {"status": "ok"}

    async def cancel_sleep(self, child_uid: str) -> dict[str, Any]:
        await self._api.cancel_sleep(child_uid)
        return {"status": "ok"}

    async def start_feeding(self, child_uid: str, side: str | None = None) -> dict[str, Any]:
        await self._api.start_nursing(child_uid, side=side or "left")
        return {"status": "ok"}

    async def pause_feeding(self, child_uid: str) -> dict[str, Any]:
        await self._api.pause_nursing(child_uid)
        return {"status": "ok"}

    async def resume_feeding(self, child_uid: str) -> dict[str, Any]:
        await self._api.resume_nursing(child_uid)
        return {"status": "ok"}

    async def switch_feeding_side(self, child_uid: str) -> dict[str, Any]:
        await self._api.switch_nursing_side(child_uid)
        return {"status": "ok"}

    async def complete_feeding(self, child_uid: str) -> dict[str, Any]:
        await self._api.complete_nursing(child_uid)
        return {"status": "ok"}

    async def cancel_feeding(self, child_uid: str) -> dict[str, Any]:
        await self._api.cancel_nursing(child_uid)
        return {"status": "ok"}

    async def log_breastfeeding(
        self,
        child_uid: str,
        left_duration_minutes: float = 0.0,
        right_duration_minutes: float = 0.0,
        last_side: str | None = None,
    ) -> dict[str, Any]:
        left_sec = left_duration_minutes * 60
        right_sec = right_duration_minutes * 60
        total_sec = left_sec + right_sec

        if last_side is None:
            last_side = "right" if right_sec >= left_sec else "left"

        now = time.time()
        start_time = now - total_sec
        interval_id = f"{int(now * 1000)}-{uuid.uuid4().hex[:20]}"
        offset = await self._api._get_timezone_offset_minutes()

        client = await self._api._get_firestore_client()
        feed_ref = client.collection("feed").document(child_uid)

        await feed_ref.collection("intervals").document(interval_id).set({
            "mode": "breast",
            "start": start_time,
            "lastSide": last_side,
            "lastUpdated": now,
            "leftDuration": left_sec,
            "rightDuration": right_sec,
            "offset": offset,
            "end_offset": offset,
        })

        await feed_ref.set({
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

    async def log_bottle_feeding(
        self,
        child_uid: str,
        amount: float,
        bottle_type: str,
        units: str,
    ) -> dict[str, Any]:
        await self._api.log_bottle(child_uid, amount=amount, bottle_type=bottle_type, units=units)
        return {"status": "ok"}

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
        await self._api.log_diaper(child_uid, **kwargs)
        return {"status": "ok"}

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
        await self._api.log_growth(child_uid, **kwargs)
        return {"status": "ok"}

    async def get_growth_data(self, child_uid: str) -> dict[str, Any]:
        result = await self._api.get_latest_growth(child_uid)
        if result is None:
            return {}
        return result.model_dump()

    async def _fetch_intervals_raw(
        self,
        collection: str,
        child_uid: str,
        start_timestamp: int,
        end_timestamp: int,
    ) -> list[dict[str, Any]]:
        """Fetch intervals from any collection as raw dicts, tolerating unknown field values.

        huckleberry_api 0.3.0 uses strict pydantic validation which fails the entire
        multi-container document if any single entry has an unrecognised value (e.g.
        bottleType='Mixed' from older app versions). This bypasses that by fetching
        raw Firestore data and skipping individual malformed entries gracefully.
        """
        from google.cloud import firestore  # type: ignore[import]

        events: list[dict[str, Any]] = []
        client = await self._api._get_firestore_client()
        intervals_ref = client.collection(collection).document(child_uid).collection("intervals")

        try:
            # Regular (non-multi) documents
            regular_docs = (
                intervals_ref
                .where(filter=firestore.FieldFilter("start", ">=", start_timestamp))
                .where(filter=firestore.FieldFilter("start", "<", end_timestamp))
                .order_by("start")
                .stream()
            )
            async for doc in regular_docs:
                data = doc.to_dict()
                if data and not data.get("multi"):
                    events.append(data)

            # Multi-container documents — iterate entries individually
            multi_docs = intervals_ref.where(filter=firestore.FieldFilter("multi", "==", True)).stream()
            async for doc in multi_docs:
                data = doc.to_dict()
                if not data:
                    continue
                for entry in data.get("data", {}).values():
                    if not isinstance(entry, dict):
                        continue
                    entry_start = entry.get("start")
                    if entry_start is not None and start_timestamp <= entry_start < end_timestamp:
                        events.append(entry)

        except Exception:
            log.exception("Error fetching raw %s intervals for child %s", collection, child_uid)

        return events

    async def get_history(
        self,
        child_uid: str,
        start_timestamp: int,
        end_timestamp: int,
        event_types: list[str] | None = None,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {}
        types = set(event_types) if event_types else {"sleep", "feed", "diaper"}

        if "sleep" in types:
            result["sleep"] = await self._fetch_intervals_raw("sleep", child_uid, start_timestamp, end_timestamp)

        if "feed" in types:
            result["feed"] = await self._fetch_intervals_raw("feed", child_uid, start_timestamp, end_timestamp)

        if "diaper" in types:
            result["diaper"] = await self._fetch_intervals_raw("diaper", child_uid, start_timestamp, end_timestamp)

        return result


# Module-level singleton (populated in main.py lifespan)
manager = HuckleberryManager()
