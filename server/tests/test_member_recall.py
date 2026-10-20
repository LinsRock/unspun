"""Recall losses before semantics, including the retained v1 failure behavior."""

import copy
import subprocess
import types
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy.orm import Session

from tests.test_content_feed import ready
from tests.test_member_processing import MemberDB
from tests.test_topics import DEFINITION, member, write
from unspun.core.member_recall import (
    current_input,
    metadata_rank,
    recall_plan,
    subject_terms,
    topic_candidate,
)
from unspun.core.models import Article
from unspun.core.topic_contracts import DefineTopic

pytest_plugins = ["tests.test_member_processing"]


@pytest.fixture
def old_recall() -> Any:
    module = types.ModuleType("retained_member_recall_v1")
    source = subprocess.check_output(
        ["git", "show", "c58a878:server/src/unspun/core/member_recall.py"], text=True
    )
    exec(compile(source, "<retained-recall-v1>", "exec"), module.__dict__)
    return module


def test_optional_empty_card_terms_use_original_material(
    member_db: MemberDB, old_recall: Any
) -> None:
    db = member_db
    with db.scope() as session:
        query = current_input(session, db.article, db.sources, datetime.now(UTC))
        query["qualification"]["card"]["payload"]["topics"] = []
        query["content"]["title"] = "DeepSeek model release"
        same, other = copy.deepcopy(query), copy.deepcopy(query)
        other["content"]["title"] = "Volcanic eruption"
        a = {"id": "a", "anchors": [{"snapshot": other}]}
        z = {"id": "z", "anchors": [{"snapshot": same}]}
        assert old_recall._metadata_rank(query, a) < old_recall._metadata_rank(query, z)
        assert metadata_rank(query, z) < metadata_rank(query, a)
        assert "deepseek" in subject_terms(query)


def test_subject_ranking_precedes_uuid_32_cutoff(member_db: MemberDB, old_recall: Any) -> None:
    db = member_db
    with db.scope() as session:
        anchor = session.get(Article, db.anchor)
        assert anchor
        title = current_input(session, db.article, db.sources, datetime.now(UTC))["content"][
            "title"
        ]
        for i in range(1, 33):
            topic = UUID(int=i)
            write(
                session,
                topic,
                DEFINITION.model_copy(update={"title": "Unrelated volcano"}),
                db.sources,
            )
            write(session, topic, member(anchor), db.sources)
        target = UUID(int=2**128 - 1)
        write(
            session,
            target,
            DefineTopic(kind="event", title=title, domains=("science",)),
            db.sources,
        )
        write(session, target, member(anchor), db.sources)
        old = old_recall.recall_plan(session, db.article, db.sources, datetime.now(UTC))
        new = recall_plan(session, db.article, db.sources, datetime.now(UTC))
        assert str(target) not in [t["id"] for t in old["topics"]]
        assert str(target) in new["trace"]["scanned_topic_ids"]
        assert len(new["trace"]["scanned_topic_ids"]) == 32
        assert new["trace"]["domain_topics"] == 34


def test_skip_first_two_stale_anchors_within_bounded_scan(
    member_db: MemberDB, old_recall: Any
) -> None:
    db = member_db
    with db.scope() as session:
        articles = [session.get(Article, db.anchor), ready(session), ready(session)]
        assert all(articles)
        for article in articles[1:]:
            assert article
            write(session, db.topic, member(article), db.sources)
        for article in articles[:2]:
            assert article
            article.url += "?changed-identity"
        session.flush()
        with pytest.raises(ValueError, match="stale"):
            old_recall.topic_candidate(session, str(db.topic), db.sources, datetime.now(UTC))
        trace: dict[str, Any] = {}
        new = topic_candidate(session, str(db.topic), db.sources, datetime.now(UTC), trace=trace)
        assert len(new["anchors"]) == 1
        assert len(trace["stale"]) == 2
        assert len(trace["checked"]) == 3


def test_unknown_and_old_background_survive_competing_recent_topics(
    member_db: MemberDB, old_recall: Any
) -> None:
    db = member_db
    with db.scope() as session:
        anchor = session.get(Article, db.anchor)
        assert anchor
        for i in range(1, 14):
            topic = UUID(int=i)
            write(session, topic, DEFINITION, db.sources)
            write(session, topic, member(anchor), db.sources)
        targets: list[str] = []
        for i, article in enumerate(
            (ready(session, age=150), ready(session, kind="modified")), 100
        ):
            topic = UUID(int=i)
            write(session, topic, DEFINITION, db.sources)
            write(session, topic, member(article, relation="background"), db.sources)
            targets.append(str(topic))
        old = old_recall.recall_plan(session, db.article, db.sources, datetime.now(UTC))
        new = recall_plan(session, db.article, db.sources, datetime.now(UTC))
        assert not set(targets).intersection(t["id"] for t in old["topics"])
        assert set(targets).issubset(t["id"] for t in new["topics"])
        assert len(new["topics"]) == 12


def test_recall_trace_exposes_ineligible_anchor_loss(member_db: MemberDB) -> None:
    db = member_db
    with Session(db.billing.engine) as session, session.begin():
        anchor = session.get(Article, db.anchor)
        assert anchor
        anchor.url += "?changed-identity"
    with db.scope() as session:
        plan = recall_plan(session, db.article, db.sources, datetime.now(UTC))
        assert plan["topics"] == []
        assert plan["trace"]["unusable_topics"][str(db.topic)]
        assert plan["trace"]["anchors"][str(db.topic)]["stale"] == [db.anchor]
