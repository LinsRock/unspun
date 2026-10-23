"""Bounded loading under retained history; engineering scale, no real quality claim."""

import json
import time
from typing import Any

import pytest
from sqlalchemy import event, text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

from tests.test_content_feed import enabled_sources as enabled_sources
from tests.test_content_feed import ready
from tests.test_hybrid_feed import feed
from tests.test_hybrid_feed import hybrid as hybrid


def test_history_does_not_expand_payloads_or_change_snapshot(
    db_session: Session, hybrid: None
) -> None:
    ready(db_session)
    ready(db_session, source="zhihu-daily", domain="culture")
    original = feed(db_session)
    template = db_session.scalar(text("SELECT min(id) FROM content_derivations WHERE kind='card'"))
    db_session.execute(
        text("""
        INSERT INTO content_derivations
            (article_id,material_id,kind,status,input_fingerprint,metadata_fingerprint,
             contract_version,generation_model,review_contract,review_model,payload,review_evidence)
        SELECT d.article_id,d.material_id,d.kind,'invalidated','r208-history-'||n,
               d.metadata_fingerprint,d.contract_version,d.generation_model,d.review_contract,
               d.review_model,d.payload,d.review_evidence
        FROM content_derivations d CROSS JOIN generate_series(1,10000) AS n WHERE d.id=:id
    """),
        {"id": template},
    )
    statements: list[str] = []

    def count(
        conn: Connection,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        statements.append(statement)

    connection = db_session.connection()
    event.listen(connection, "before_cursor_execute", count)
    try:
        start = time.perf_counter()
        after = feed(db_session)
        elapsed = time.perf_counter() - start
    finally:
        event.remove(connection, "before_cursor_execute", count)
    assert after == original
    assert len(statements) <= 12
    assert len(db_session.identity_map) < 100
    print(
        json.dumps(
            {
                "history_rows": 10000,
                "current_candidates": 2,
                "sql_statements": len(statements),
                "seconds": round(elapsed, 4),
                "unchanged_snapshot": True,
            }
        )
    )


@pytest.mark.parametrize("sort", ["recommended", "latest"])
def test_candidate_bound_is_shared_but_not_oldest_id_truncation(
    db_session: Session, hybrid: None, monkeypatch: pytest.MonkeyPatch, sort: str
) -> None:
    from unspun.core.hybrid_contracts import HybridRules

    for age in range(10, 2, -1):
        ready(db_session, age=age)
    newest = ready(db_session, age=0)
    diverse = ready(db_session, source="zhihu-daily", domain="culture", age=1)
    monkeypatch.setattr(
        "unspun.core.hybrid_feed.hybrid_rules", lambda: HybridRules(readable_limit=2)
    )
    result = feed(db_session, sort=sort)
    assert {i["id"] for i in result["items"]} == {str(newest.id), str(diverse.id)}


def test_maximum_fusion_pool_has_bounded_work() -> None:
    from tests.test_hybrid_feed import candidate
    from unspun.core.content_feed import rules
    from unspun.core.hybrid_contracts import HybridRules
    from unspun.core.hybrid_ranking import ordered

    pool = [candidate(str(i), source=str(i % 8), domain=str(i % 5)) for i in range(632)]
    start = time.perf_counter()
    result = ordered(pool, "recommended", HybridRules(), rules())
    elapsed = time.perf_counter() - start
    assert len(result) == len({c.key for c, _ in result}) == 632
    print(json.dumps({"maximum_candidates": 632, "ranking_seconds": round(elapsed, 4)}))
