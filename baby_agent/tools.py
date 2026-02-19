"""Claude tool JSON schemas and async dispatcher for Huckleberry actions."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from .config import settings
from .huckleberry import HuckleberryManager

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool definitions (Anthropic API format)
# ---------------------------------------------------------------------------

# Shared child_uid property used across many tools
_CHILD_UID_PROP = {
    "child_uid": {
        "type": "string",
        "description": "Child UID to act on. If omitted the primary child is used.",
    }
}

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "get_current_state",
        "description": "Get the current live state for a child (sleep status, feeding status, etc.).",
        "input_schema": {
            "type": "object",
            "properties": {**_CHILD_UID_PROP},
        },
    },
    # ---- Sleep ----
    {
        "name": "start_sleep",
        "description": "Start tracking a sleep session for the child right now.",
        "input_schema": {
            "type": "object",
            "properties": {**_CHILD_UID_PROP},
        },
    },
    {
        "name": "pause_sleep",
        "description": "Pause the active sleep session (e.g., baby woke briefly).",
        "input_schema": {
            "type": "object",
            "properties": {**_CHILD_UID_PROP},
        },
    },
    {
        "name": "resume_sleep",
        "description": "Resume a paused sleep session.",
        "input_schema": {
            "type": "object",
            "properties": {**_CHILD_UID_PROP},
        },
    },
    {
        "name": "complete_sleep",
        "description": "End and save the active sleep session.",
        "input_schema": {
            "type": "object",
            "properties": {**_CHILD_UID_PROP},
        },
    },
    {
        "name": "cancel_sleep",
        "description": "Cancel and discard the active sleep session without saving.",
        "input_schema": {
            "type": "object",
            "properties": {**_CHILD_UID_PROP},
        },
    },
    # ---- Breastfeeding ----
    {
        "name": "start_feeding",
        "description": "Start tracking a breastfeeding session.",
        "input_schema": {
            "type": "object",
            "properties": {
                **_CHILD_UID_PROP,
                "side": {
                    "type": "string",
                    "enum": ["left", "right"],
                    "description": "Which breast to start on (optional).",
                },
            },
        },
    },
    {
        "name": "pause_feeding",
        "description": "Pause the active feeding session.",
        "input_schema": {
            "type": "object",
            "properties": {**_CHILD_UID_PROP},
        },
    },
    {
        "name": "resume_feeding",
        "description": "Resume a paused feeding session.",
        "input_schema": {
            "type": "object",
            "properties": {**_CHILD_UID_PROP},
        },
    },
    {
        "name": "switch_feeding_side",
        "description": "Switch to the other breast during an active feeding session.",
        "input_schema": {
            "type": "object",
            "properties": {**_CHILD_UID_PROP},
        },
    },
    {
        "name": "complete_feeding",
        "description": "End and save the active feeding session.",
        "input_schema": {
            "type": "object",
            "properties": {**_CHILD_UID_PROP},
        },
    },
    {
        "name": "cancel_feeding",
        "description": "Cancel and discard the active feeding session without saving.",
        "input_schema": {
            "type": "object",
            "properties": {**_CHILD_UID_PROP},
        },
    },
    # ---- Bottle feeding ----
    {
        "name": "log_bottle_feeding",
        "description": "Log a completed bottle feeding session.",
        "input_schema": {
            "type": "object",
            "properties": {
                **_CHILD_UID_PROP,
                "amount": {
                    "type": "number",
                    "description": "Volume of milk/formula given.",
                },
                "bottle_type": {
                    "type": "string",
                    "enum": ["Breast Milk", "Formula", "Mixed"],
                    "description": "Type of liquid in the bottle.",
                },
                "units": {
                    "type": "string",
                    "enum": ["oz", "ml"],
                    "description": "Unit of measurement for the amount.",
                },
            },
            "required": ["amount", "bottle_type", "units"],
        },
    },
    # ---- Diaper ----
    {
        "name": "log_diaper",
        "description": (
            "Log a diaper change. "
            "Use mode='pee' for wet/pee-only diapers, "
            "'poo' for dirty/poo-only diapers, "
            "'both' for mixed wet-and-dirty diapers, "
            "'dry' for a dry check."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                **_CHILD_UID_PROP,
                "mode": {
                    "type": "string",
                    "enum": ["pee", "poo", "both", "dry"],
                    "description": (
                        "Diaper type: 'pee' (wet only), 'poo' (dirty/poo only), "
                        "'both' (wet and dirty), 'dry' (no change needed)."
                    ),
                },
                "pee_amount": {
                    "type": "string",
                    "enum": ["little", "medium", "big"],
                    "description": "Amount of pee (optional).",
                },
                "poo_amount": {
                    "type": "string",
                    "enum": ["little", "medium", "big"],
                    "description": "Amount of poo (optional).",
                },
                "color": {
                    "type": "string",
                    "enum": ["yellow", "brown", "black", "green", "red", "gray"],
                    "description": "Color of the stool.",
                },
                "consistency": {
                    "type": "string",
                    "enum": ["solid", "loose", "runny", "mucousy", "hard", "pebbles", "diarrhea"],
                    "description": "Consistency of the stool.",
                },
            },
            "required": ["mode"],
        },
    },
    # ---- Growth ----
    {
        "name": "log_growth",
        "description": "Log a growth measurement (weight, height, head circumference).",
        "input_schema": {
            "type": "object",
            "properties": {
                **_CHILD_UID_PROP,
                "weight": {"type": "number", "description": "Weight measurement."},
                "height": {"type": "number", "description": "Height/length measurement."},
                "head": {"type": "number", "description": "Head circumference measurement."},
                "units": {
                    "type": "string",
                    "enum": ["imperial", "metric"],
                    "description": "Unit system: imperial (lbs/in) or metric (kg/cm). Default: imperial.",
                },
            },
        },
    },
    {
        "name": "get_growth_data",
        "description": "Retrieve historical growth data for a child.",
        "input_schema": {
            "type": "object",
            "properties": {**_CHILD_UID_PROP},
        },
    },
    {
        "name": "get_history",
        "description": (
            "Retrieve historical records (sleep sessions, feedings, diapers) for a given date. "
            "Use this to answer questions like 'how many times did Henry sleep today?', "
            "'when was the last diaper?', or 'how long did the last nap last?'. "
            "Defaults to today if no date is provided."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                **_CHILD_UID_PROP,
                "date": {
                    "type": "string",
                    "description": "Date to query in YYYY-MM-DD format. Defaults to today.",
                },
                "event_types": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": ["sleep", "feed", "diaper", "health"],
                    },
                    "description": "Which event types to include. Defaults to all types.",
                },
            },
        },
        "cache_control": {"type": "ephemeral"},
    },
]


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

async def dispatch_tool(
    name: str,
    inputs: dict[str, Any],
    manager: HuckleberryManager,
) -> dict[str, Any]:
    """Execute a tool by name and return a JSON-serialisable result dict."""
    # Resolve child_uid — fall back to primary child if not provided
    child_uid: str | None = inputs.get("child_uid") or manager.get_primary_child_uid()
    if child_uid is None:
        return {"error": "No child found. Please check Huckleberry setup."}

    try:
        match name:
            case "get_current_state":
                return await manager.get_current_state(child_uid)

            case "start_sleep":
                return await manager.start_sleep(child_uid)

            case "pause_sleep":
                return await manager.pause_sleep(child_uid)

            case "resume_sleep":
                return await manager.resume_sleep(child_uid)

            case "complete_sleep":
                return await manager.complete_sleep(child_uid)

            case "cancel_sleep":
                return await manager.cancel_sleep(child_uid)

            case "start_feeding":
                return await manager.start_feeding(child_uid, side=inputs.get("side"))

            case "pause_feeding":
                return await manager.pause_feeding(child_uid)

            case "resume_feeding":
                return await manager.resume_feeding(child_uid)

            case "switch_feeding_side":
                return await manager.switch_feeding_side(child_uid)

            case "complete_feeding":
                return await manager.complete_feeding(child_uid)

            case "cancel_feeding":
                return await manager.cancel_feeding(child_uid)

            case "log_bottle_feeding":
                return await manager.log_bottle_feeding(
                    child_uid,
                    amount=float(inputs["amount"]),
                    bottle_type=inputs["bottle_type"],
                    units=inputs["units"],
                )

            case "log_diaper":
                return await manager.log_diaper(
                    child_uid,
                    mode=inputs["mode"],
                    pee_amount=inputs.get("pee_amount"),
                    poo_amount=inputs.get("poo_amount"),
                    color=inputs.get("color"),
                    consistency=inputs.get("consistency"),
                )

            case "log_growth":
                return await manager.log_growth(
                    child_uid,
                    weight=inputs.get("weight"),
                    height=inputs.get("height"),
                    head=inputs.get("head"),
                    units=inputs.get("units", "imperial"),
                )

            case "get_growth_data":
                return await manager.get_growth_data(child_uid)

            case "get_history":
                tz = ZoneInfo(settings.huckleberry_timezone)
                date_str = inputs.get("date")
                if date_str:
                    d = datetime.strptime(date_str, "%Y-%m-%d").date()
                else:
                    d = datetime.now(tz).date()
                start_dt = datetime(d.year, d.month, d.day, tzinfo=tz)
                end_dt = start_dt + timedelta(days=1)
                result = await manager.get_history(
                    child_uid,
                    int(start_dt.timestamp()),
                    int(end_dt.timestamp()),
                )
                event_types = inputs.get("event_types")
                if event_types:
                    result = {k: v for k, v in result.items() if k in event_types}
                return result

            case _:
                return {"error": f"Unknown tool: {name}"}

    except Exception as exc:
        log.exception("Tool %s raised an exception", name)
        return {"error": str(exc)}
