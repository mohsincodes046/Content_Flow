from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import ALLOWED_ORIGINS, publisher_interval_seconds, publisher_is_enabled
from app.database import initialize_storage
from app.observability import RequestIdMiddleware, configure_logging
from app.publisher import recover_interrupted, run_publisher_scheduler
from app.routers import ai, analytics, assets, auth, posts, social, submissions, webhooks, workspaces

configure_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_storage()
    publisher_task = None
    if publisher_is_enabled():
        publisher_interval_seconds()
        recover_interrupted()
        publisher_task = asyncio.create_task(run_publisher_scheduler())
    try:
        yield
    finally:
        if publisher_task is not None:
            publisher_task.cancel()
            try:
                await publisher_task
            except asyncio.CancelledError:
                pass


app = FastAPI(
    title="Content-Flow API",
    description="Content Flow: social media planning, approval and publishing.",
    version="0.1.0",
    lifespan=lifespan,
)

# Added before CORS so CORS stays the outermost layer and also covers JSON 500 responses.
app.add_middleware(RequestIdMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Content-Type"],
    expose_headers=["X-Request-ID", "Retry-After"],
)


@app.get("/api/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(auth.router)
app.include_router(social.router)
app.include_router(ai.router)
app.include_router(posts.router)
app.include_router(analytics.router)
app.include_router(assets.router)
app.include_router(submissions.router)
app.include_router(webhooks.router)
app.include_router(workspaces.router)
