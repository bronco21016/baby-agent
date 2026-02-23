"""FastAPI application entrypoint for baby-agent."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

import anthropic
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .agent import run_turn
from .config import settings
from .conversation_log import append_turn, prune_old_entries, prune_task
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
    prune_old_entries()
    cleanup_task = asyncio.create_task(session_cleanup_task())
    log_prune_task = asyncio.create_task(prune_task())
    log.info("baby-agent ready.")
    yield
    log.info("Shutting down…")
    cleanup_task.cancel()
    log_prune_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass
    try:
        await log_prune_task
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
    conversation_done: bool


# ---------------------------------------------------------------------------
# Conversation-done classifier
# ---------------------------------------------------------------------------

_classifier_client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

_DONE_SYSTEM = (
    "You decide if a baby-care assistant conversation is finished. "
    "Reply with exactly one word: YES or NO.\n"
    "Reply YES if the user's message is a closing statement (thanks, bye, that's all, "
    "done, got it, perfect, all set, etc.) OR the exchange is clearly a completed "
    "one-shot action with no follow-up expected.\n"
    "Reply NO if the conversation is ongoing or the user may want to do more."
)


async def _is_conversation_done(user_message: str, agent_reply: str) -> bool:
    """Use Claude Haiku to decide whether the conversation should end."""
    prompt = f"User said: {user_message!r}\nAssistant replied: {agent_reply!r}"
    try:
        resp = await _classifier_client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=5,
            system=_DONE_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text.strip().upper() if resp.content else ""
        return text.startswith("YES")
    except Exception:
        log.exception("conversation_done classifier failed; defaulting to False")
        return False


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

    done = await _is_conversation_done(req.message, reply)

    append_turn(
        session_id=req.session_id,
        turn=session.turn_count,
        user=req.message,
        reply=reply,
        conversation_done=done,
    )

    return MessageResponse(
        session_id=req.session_id,
        reply=reply,
        turn_count=session.turn_count,
        conversation_done=done,
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
