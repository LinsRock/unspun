"""Authenticated, read-only topic reading routes."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from unspun.api.admin.auth import require_admin_identity
from unspun.api.contents import ReadDb
from unspun.core.config import get_settings
from unspun.core.sources import load_sources
from unspun.core.topic_reading import topic_detail

router = APIRouter(dependencies=[Depends(require_admin_identity)])


@router.get("/api/reading-capabilities")
def reading_capabilities() -> dict[str, Any]:
    settings = get_settings()
    return {
        "hybrid": settings.r2_hybrid_enabled,
        "topic_preferences": settings.r2_topic_preferences_enabled,
        "home": "discover"
        if settings.r2_discover_home_enabled and settings.r2_hybrid_enabled
        else "events",
        "engineering_preview": False,
    }


@router.get("/api/topics/{topic_id}")
def details(topic_id: UUID, session: ReadDb) -> dict[str, Any]:
    result = topic_detail(session, topic_id, sources=load_sources(), now=datetime.now(UTC))
    if result is None:
        raise HTTPException(404, "Current reviewed topic is not published")
    return result
