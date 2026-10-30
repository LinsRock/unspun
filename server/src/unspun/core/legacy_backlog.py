"""Shared read-only legacy backlog queries for reports and retained processing."""

from typing import Any

from sqlalchemy import ColumnElement, case, func, or_, select
from sqlalchemy.orm import Session

from unspun.core.content import legacy_event_condition
from unspun.core.models import Article, Event
from unspun.core.params import get_scoring_params
from unspun.core.reading import READING_VERSION, input_hash_expression, ready_condition


def pending_summary_conditions() -> tuple[ColumnElement[bool], ...]:
    return (
        or_(
            Article.summary_zh.is_(None),
            func.coalesce(Article.summary_grounding["reading"]["input_hash"].astext, "")
            != input_hash_expression(),
            Article.summary_grounding["status"].astext == "review_limited",
            Article.summary_grounding["reading"]["reason"].astext.in_(
                ["language_invalid", "title_unverified"]
            ),
            (
                func.coalesce(Article.summary_grounding["reading"]["version"].astext, "")
                != READING_VERSION
            ),
        ),
        Article.summary_failures < get_scoring_params().pipeline.max_summary_failures,
        Article.processing_track == "legacy",
    )


def abandoned_summary_conditions() -> tuple[ColumnElement[bool], ...]:
    return (
        pending_summary_conditions()[0],
        Article.summary_failures >= get_scoring_params().pipeline.max_summary_failures,
        Article.processing_track == "legacy",
    )


def pending_embedding_conditions() -> tuple[ColumnElement[bool], ...]:
    return (ready_condition(), Article.embedding.is_(None), Article.processing_track == "legacy")


def summary_ordering() -> tuple[Any, ...]:
    return (
        Article.published_at.desc().nulls_last(),
        case((Article.summary_grounding["status"].astext == "review_limited", 0), else_=1),
        Article.id.desc(),
    )


def pending_score_conditions() -> tuple[ColumnElement[bool], ...]:
    # Historical backlog reporting remains available after batch retirement.
    return (
        or_(Event.scored_at.is_(None), Event.changed_at > Event.scored_at),
        legacy_event_condition(),
    )


def backlog_counts(session: Session) -> dict[str, int]:
    return {
        "pending_summaries": session.scalar(
            select(func.count()).select_from(Article).where(*pending_summary_conditions())
        )
        or 0,
        "pending_embeddings": session.scalar(
            select(func.count()).select_from(Article).where(*pending_embedding_conditions())
        )
        or 0,
        "pending_scores": session.scalar(
            select(func.count()).select_from(Event).where(*pending_score_conditions())
        )
        or 0,
        "abandoned_summaries": session.scalar(
            select(func.count()).select_from(Article).where(*abandoned_summary_conditions())
        )
        or 0,
    }
