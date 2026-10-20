"""Replay deployed read paths in a SELECT-only transaction without changing the service."""

import json
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session
from unspun.api.contents import find_item, guide_state
from unspun.core.config import get_settings
from unspun.core.content_feed import page, reviewed, rules
from unspun.core.db import get_engine
from unspun.core.sources import load_sources

out = {
    "checked_at": datetime.now(UTC).isoformat(),
    "app_version": get_settings().app_version,
    "mode": "deployed Python read-path replay, not external authenticated browser evidence",
    "paid_calls": 0,
    "manual_tasks_triggered": 0,
}
with (
    get_engine().connect().execution_options(isolation_level="REPEATABLE READ") as connection,
    connection.begin() as transaction,
    Session(bind=connection) as session,
):
    connection.execute(text("SET TRANSACTION READ ONLY"))
    connection.execute(text("SET LOCAL statement_timeout = '30s'"))
    now = connection.scalar(text("SELECT transaction_timestamp()"))
    out["transaction"] = dict(
        connection.execute(
            text(
                "SELECT current_database() AS database, "
                "current_setting('transaction_read_only') AS read_only"
            )
        )
        .mappings()
        .one()
    )
    before = connection.scalar(text("SELECT count(*) FROM pipeline_tasks"))
    sources = load_sources()
    items = reviewed(session, preview=False, as_of=now, sources=sources, policy=rules())
    out["published_ids"] = [item.article.id for item in items]
    out["feed"] = {}
    for sort in ("recommended", "latest"):
        first = page(session, preview=False, sort=sort, cursor=None, limit=2, now=now)
        next_page = (
            page(session, preview=False, sort=sort, cursor=first["next_cursor"], limit=2, now=now)
            if first["next_cursor"]
            else None
        )
        out["feed"][sort] = {
            "first_ids": [item["id"] for item in first["items"]],
            "second_ids": [item["id"] for item in next_page["items"]] if next_page else [],
            "ranking_version": first["ranking_version"],
            "preview": first["preview"],
        }
    if items:
        item, alias = find_item(session, items[0].article.id, False)
        out["detail"] = {
            "id": item.article.id,
            "material_id": item.content.material_id,
            "scope": item.content.scope,
            "alias": alias,
            "guide_status": guide_state(session, item)["status"],
        }
    try:
        find_item(session, 8844, False)
        out["suspended_nyt_status"] = 200
    except HTTPException as error:
        out["suspended_nyt_status"] = error.status_code
    out["tasks_before"] = before
    out["tasks_after"] = connection.scalar(text("SELECT count(*) FROM pipeline_tasks"))
    transaction.rollback()
print(json.dumps(out, default=str, indent=2))
