"""JSONL conversation logger with automatic pruning of entries older than 7 days."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

from .config import settings

log = logging.getLogger(__name__)

_RETENTION_DAYS = 7


def _log_path() -> Path:
    return Path(settings.conversation_log_path)


def append_turn(
    *,
    session_id: str,
    turn: int,
    user: str,
    reply: str,
    conversation_done: bool,
) -> None:
    """Append one turn as a JSON line to the conversation log."""
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "session_id": session_id,
        "turn": turn,
        "user": user,
        "reply": reply,
        "conversation_done": conversation_done,
    }
    try:
        with _log_path().open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except Exception:
        log.exception("Failed to write conversation log entry")


def prune_old_entries() -> int:
    """Remove entries older than _RETENTION_DAYS. Returns number of lines removed."""
    path = _log_path()
    if not path.exists():
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=_RETENTION_DAYS)
    kept: list[str] = []
    removed = 0
    try:
        with path.open("r", encoding="utf-8") as f:
            for raw in f:
                line = raw.rstrip("\n")
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    ts = datetime.fromisoformat(record["ts"])
                    if ts >= cutoff:
                        kept.append(line)
                    else:
                        removed += 1
                except Exception:
                    # Keep malformed lines to avoid silent data loss
                    kept.append(line)
        with path.open("w", encoding="utf-8") as f:
            for line in kept:
                f.write(line + "\n")
    except Exception:
        log.exception("Failed to prune conversation log")
        return 0
    if removed:
        log.info("Pruned %d old conversation log entry/entries.", removed)
    return removed


async def prune_task() -> None:
    """Background coroutine: prune old log entries once every 24 hours."""
    while True:
        await asyncio.sleep(86400)
        prune_old_entries()
