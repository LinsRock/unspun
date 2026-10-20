import json
import subprocess
import sys
import time
import types
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import HTTPException
from psycopg.types.json import Jsonb
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session
from tests.test_content_feed import NOW, ready
from tests.test_content_retrieval import clone_ready
from unspun.core.config import get_settings
from unspun.core.content_feed import candidate_versions, rank, reviewed, rules
from unspun.core.content_publication import (
    current_versions,
    qualified_item,
)
from unspun.core.models import Article, ContentDerivation
from unspun.core.sources import load_sources

settings = get_settings()
assert settings.database_url.endswith("/unspun_r2_detail_tests_20261020"), (
    "only the new migrated isolated test database is allowed"
)
engine = create_engine(settings.database_url)
sources = []
for raw in load_sources():
    if raw.id in {"xinhua", "zhihu-daily"}:
        sources.append(
            raw.model_copy(
                update={
                    "discovery_owner": "r1",
                    "legacy_enabled": False,
                    "r1": raw.r1.model_copy(
                        update={
                            "publish": True,
                            "paid": True,
                            "paid_scopes": None,
                            "publish_scopes": None,
                        }
                    ),
                }
            )
        )
# Execute only the fixed, trusted repository baseline for a before/after comparison.
old = types.ModuleType("r2_03_old_feed")
sys.modules[old.__name__] = old
exec(  # noqa: S102
    compile(
        subprocess.check_output(
            ["git", "show", "3a67836:server/src/unspun/core/content_feed.py"], text=True
        ),
        "<main-content-feed>",
        "exec",
    ),
    old.__dict__,
)
output = {
    "version": "r2-03-query-cost-v1",
    "checked_at": datetime.now(UTC).isoformat(),
    "database": engine.url.database,
    "mode": (
        "synthetic mock-reviewed inputs; all inserts and ANALYZE "
        "in an isolated rollback transaction"
    ),
    "paid_calls": 0,
    "scenarios": {},
}
with engine.connect() as conn, conn.begin() as tx, Session(bind=conn) as session:
    ids = clone_ready(session, 1105, genre="news")
    oldids = clone_ready(session, 1105, genre="news")
    from sqlalchemy import update

    session.execute(
        update(ContentDerivation)
        .where(ContentDerivation.article_id.in_(oldids))
        .values(contract_version="obsolete")
    )
    expired = clone_ready(session, 1105, genre="news", age=13)
    knowledge = ready(session, age=1000, source="zhihu-daily")
    unknown = ready(session, kind="feed")
    session.flush()
    conn.execute(
        text("ANALYZE articles, content_materials, content_derivations, content_observations")
    )
    at = NOW + timedelta(days=2)
    output["population"] = {
        "articles": 3317,
        "raw_ready_card_rows": 3317,
        "obsolete_contract_cards": 1105,
        "expired_news_cards": 1105,
        "eligible_current_cards": 1107,
        "candidate_bound": 1000,
    }
    for name, query in [
        (
            "candidate_ids",
            candidate_versions(preview=False, as_of=at, sources=sources, bound=1000),
        ),
        (
            "detail_version",
            current_versions(preview=False, as_of=at, sources=sources).where(Article.id == ids[0]),
        ),
    ]:
        compiled = query.compile(
            dialect=engine.dialect, compile_kwargs={"render_postcompile": True}
        )
        params = {
            key: Jsonb(value) if isinstance(value, (dict, list)) else value
            for key, value in compiled.params.items()
        }
        result = conn.exec_driver_sql(
            "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + str(compiled), params
        ).scalar_one()
        output["scenarios"][name] = {"plan": result}
    statements = []

    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(conn, "before_cursor_execute", record)
    try:
        for name, fn in [
            (
                "old_reviewed",
                lambda: old.reviewed(
                    session,
                    preview=False,
                    as_of=at,
                    sources=sources,
                    policy=rules(),
                ),
            ),
            (
                "new_reviewed",
                lambda: reviewed(
                    session,
                    preview=False,
                    as_of=at,
                    sources=sources,
                    policy=rules(),
                ),
            ),
            (
                "new_detail",
                lambda: qualified_item(session, ids[0], preview=False, as_of=at, sources=sources),
            ),
        ]:
            statements.clear()
            start = time.perf_counter()
            try:
                value = fn()
                outcome = {
                    "status": 200,
                    "loaded_items": len(value)
                    if isinstance(value, list)
                    else int(value is not None),
                }
            except HTTPException as error:
                outcome = {"status": error.status_code, "detail": error.detail}
            output["scenarios"][name] = {
                **outcome,
                "sql_statements": len(statements),
                "elapsed_ms": round((time.perf_counter() - start) * 1000, 3),
            }
    finally:
        event.remove(conn, "before_cursor_execute", record)
    items = reviewed(session, preview=False, as_of=at, sources=sources, policy=rules())
    started = time.perf_counter()
    ranked, _ = rank(session, items, at, "recommended", rules())
    output["scenarios"]["unchanged_recommended_rank"] = {
        "items": len(ranked),
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
        "note": "Scoring/diversity CPU, separately measured from SQL and input validation.",
    }
    tx.rollback()
Path(sys.argv[1]).write_text(json.dumps(output, default=str, indent=2) + "\n")
print(
    {
        name: {k: v for k, v in data.items() if k != "plan"}
        for name, data in output["scenarios"].items()
    }
)
