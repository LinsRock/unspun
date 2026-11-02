"""Offline replay of retired HTTP contracts; never registered by the runtime app."""

from fastapi import FastAPI

from unspun.evaluation.legacy.digest_api import router as digest_router
from unspun.evaluation.legacy.events import router as events_router
from unspun.evaluation.legacy.feed_preferences import router as preferences_router

app = FastAPI()
app.include_router(events_router)
app.include_router(digest_router)
app.include_router(preferences_router)
