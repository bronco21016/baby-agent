"""FastAPI application entrypoint for baby-agent."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .agent import run_turn
from .config import settings
from .huckleberry import manager
from .session import session_cleanup_task, store

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Starting up baby-agent…")
    await manager.startup()
    cleanup_task = asyncio.create_task(session_cleanup_task())
    log.info("baby-agent ready.")
    yield
    log.info("Shutting down…")
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass
    await manager.teardown()
    log.info("Shutdown complete.")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="baby-agent", version="0.1.0", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class MessageRequest(BaseModel):
    session_id: str
    message: str


class MessageResponse(BaseModel):
    session_id: str
    reply: str
    turn_count: int


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "huckleberry_authenticated": manager.authenticated,
        "active_children": [
            {"uid": c["uid"], "name": c.get("name")} for c in manager.children
        ],
        "active_sessions": await store.active_count(),
    }


@app.post("/message", response_model=MessageResponse)
async def message(req: MessageRequest):
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="message must not be empty")

    if not manager.authenticated:
        raise HTTPException(status_code=503, detail="Huckleberry not authenticated")

    if not manager.children:
        raise HTTPException(status_code=503, detail="No children found in Huckleberry account")

    session = await store.get_or_create(req.session_id)

    try:
        reply, updated_history = await run_turn(
            user_message=req.message,
            history=session.history,
            manager=manager,
        )
    except Exception as exc:
        log.exception("Agent error for session %s", req.session_id)
        raise HTTPException(status_code=500, detail=f"Agent error: {exc}") from exc

    session.history = updated_history
    session.turn_count += 1
    await store.save(session)

    return MessageResponse(
        session_id=req.session_id,
        reply=reply,
        turn_count=session.turn_count,
    )


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

def run() -> None:
    uvicorn.run(
        "baby_agent.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    run()
