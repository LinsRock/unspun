"""SELECT-only replay of deployed reading functions; not an external browser/auth check."""

import hashlib
import json
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from unspun.api.contents import find_item
from unspun.core.content_feed import page, reviewed, rules
from unspun.core.db import get_engine
from unspun.core.sources import load_sources

out = {
    "captured_at": datetime.now(UTC).isoformat(),
    "external_browser_acceptance": None,
}
with (
    get_engine().connect().execution_options(isolation_level="REPEATABLE READ") as conn
):
    tx = conn.begin()
    conn.execute(text("SET TRANSACTION READ ONLY"))
    conn.execute(text("SET LOCAL statement_timeout='30s'"))
    session = Session(bind=conn)
    out["read_only"] = conn.scalar(
        text("SELECT current_setting('transaction_read_only')")
    )
    out["tasks_before"] = conn.scalar(text("SELECT count(*) FROM pipeline_tasks"))
    now = conn.scalar(text("SELECT transaction_timestamp()"))
    items = reviewed(
        session, preview=False, as_of=now, sources=load_sources(), policy=rules()
    )
    out["published_ids"] = sorted(item.article.id for item in items)
    out["published_by_source"] = {
        source_id: sum(item.article.source_id == source_id for item in items)
        for source_id in sorted({item.article.source_id for item in items})
    }
    out["new_path_published"] = sum(
        item.article.source_id in {"thepaper-sidebar", "36kr-newsflashes"}
        for item in items
    )
    out["qualified_details_verified"] = []
    for item in items:
        qualified, alias = find_item(session, item.article.id, False)
        out["qualified_details_verified"].append(
            {
                "id": qualified.article.id,
                "scope": qualified.content.scope,
                "body_sha256": hashlib.sha256(
                    qualified.content.text().encode()
                ).hexdigest(),
                "alias": alias,
            }
        )
    for sort in ("recommended", "latest"):
        first = page(session, preview=False, sort=sort, cursor=None, limit=20, now=now)
        second = (
            page(
                session,
                preview=False,
                sort=sort,
                cursor=first["next_cursor"],
                limit=20,
                now=now,
            )
            if first["next_cursor"]
            else None
        )
        out[sort] = {
            "first_ids": [item["id"] for item in first["items"]],
            "second_ids": [item["id"] for item in second["items"]]
            if second
            else [],
        }
    try:
        find_item(session, 8844, False)
    except HTTPException as error:
        out["suspended_nyt_status"] = error.status_code
    out["tasks_after"] = conn.scalar(text("SELECT count(*) FROM pipeline_tasks"))
    session.close()
    tx.rollback()
out.update(paid_requests=0, database_writes=0)
print(json.dumps(out, ensure_ascii=False, indent=2))
