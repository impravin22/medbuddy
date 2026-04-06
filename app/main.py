"""FastAPI application — MedBuddy LINE webhook entry point.

The webhook receives LINE events, validates signatures, and dispatches
to handlers via background tasks with a task registry.
"""

import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response

from app.config import settings
from app.database import async_session_factory
from app.handlers.message_handler import handle_message_event
from app.handlers.onboarding_handler import handle_follow_event
from app.services import line_service
from app.services.pipeline import compile_pipeline

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

# Task registry — prevents garbage collection of background tasks
_running_tasks: set[asyncio.Task] = set()

# Pipeline — compiled at startup
_pipeline = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """App lifespan — initialise pipeline and cleanup on shutdown."""
    global _pipeline
    _pipeline = compile_pipeline(checkpointer=None)
    logger.info("MedBuddy pipeline compiled and ready")
    yield
    for task in _running_tasks:
        task.cancel()
    logger.info("MedBuddy shutdown complete")


app = FastAPI(
    title="MedBuddy",
    description="AI medication assistant for elderly users",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok", "service": "medbuddy"}


@app.post("/webhook/line")
async def line_webhook(request: Request) -> Response:
    """LINE webhook endpoint.

    1. Validates X-Line-Signature
    2. Dispatches events to handlers via background tasks
    3. Returns 200 immediately (LINE requires <5s)
    """
    body = await request.body()
    signature = request.headers.get("X-Line-Signature", "")

    if not line_service.validate_signature(body, signature):
        logger.warning("Invalid LINE webhook signature")
        return Response(status_code=403)

    try:
        body_json = json.loads(body)
    except json.JSONDecodeError:
        logger.warning("Invalid JSON in webhook body")
        return Response(status_code=400)

    events = line_service.parse_webhook_events(body_json)

    for event in events:
        event_type = event.get("type", "")

        if event_type == "message":
            task = asyncio.create_task(_dispatch_message(event))
            _running_tasks.add(task)
            task.add_done_callback(_running_tasks.discard)
        elif event_type == "follow":
            task = asyncio.create_task(_dispatch_follow(event))
            _running_tasks.add(task)
            task.add_done_callback(_running_tasks.discard)

    return Response(status_code=200)


async def _dispatch_message(event: dict) -> None:
    """Dispatch a message event with a fresh DB session."""
    async with async_session_factory() as session:
        try:
            await handle_message_event(event, _pipeline, session)
        except Exception:
            logger.exception("Unhandled error in message handler")
            await session.rollback()


async def _dispatch_follow(event: dict) -> None:
    """Dispatch a follow event (new user) with a fresh DB session."""
    user_id = event.get("source", {}).get("userId", "")
    if not user_id:
        return
    async with async_session_factory() as session:
        try:
            await handle_follow_event(user_id, session)
        except Exception:
            logger.exception("Unhandled error in follow handler")
            await session.rollback()
