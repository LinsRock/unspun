"""Chinese titles/summaries (small model) and embeddings for new articles."""

import json
from itertools import batched

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from unspun.core.config import get_settings
from unspun.core.db import session_scope
from unspun.core.llm import LlmError, SupportsLlm
from unspun.core.logging import get_logger
from unspun.core.models import Article

log = get_logger("unspun.pipeline.summarize")

SUMMARY_SYSTEM = (
    "You summarize news articles for a personal intelligence reader. "
    'Respond with a JSON object: {"title_zh": "...", "summary_zh": "..."}. '
    "title_zh is the story title in Simplified Chinese (translate when the "
    "original is not Chinese). summary_zh is 2-4 factual sentences in "
    "Simplified Chinese covering what happened, who is involved, and concrete "
    "numbers from the text; no opinions, no hype."
)

MAX_CONTENT_CHARS = 6000
SUMMARY_BATCH_LIMIT = 50  # articles per cycle, bounds one cycle's spend
MAX_SUMMARY_FAILURES = 3  # give up on an article after this many failed cycles
EMBED_BATCH_SIZE = 32
EMBED_BATCH_LIMIT = 200


def summarize_article(session: Session, client: SupportsLlm, article: Article) -> None:
    body = (article.content or "")[:MAX_CONTENT_CHARS]
    user = f"Source language: {article.lang or 'unknown'}\nTitle: {article.title}\n\n{body}"
    out = client.chat_json(
        session,
        model=get_settings().summary_model,
        system=SUMMARY_SYSTEM,
        user=user,
        purpose="summary",
    )
    summary_zh = str(out.get("summary_zh") or "").strip()
    if not summary_zh:
        raise LlmError("model returned an empty summary_zh")
    article.summary_zh = summary_zh
    article.title_zh = str(out.get("title_zh") or "").strip() or article.title


def embed_articles(session: Session, client: SupportsLlm, articles: list[Article]) -> None:
    texts = [f"{a.title_zh or a.title}\n{a.summary_zh or ''}" for a in articles]
    for article, vector in zip(articles, client.embed(session, texts), strict=True):
        article.embedding = vector


def pending_summary_ids(session: Session, limit: int) -> list[int]:
    return list(
        session.scalars(
            select(Article.id)
            .where(
                Article.summary_zh.is_(None),
                Article.summary_failures < MAX_SUMMARY_FAILURES,
            )
            .order_by(Article.id)
            .limit(limit)
        )
    )


def record_summary_failure(article_id: int) -> None:
    # Must never raise: it runs in the per-article error path, and an escaping
    # exception here would abort the rest of the batch and the later stages.
    try:
        with session_scope() as session:
            failures = session.execute(
                update(Article)
                .where(Article.id == article_id)
                .values(summary_failures=Article.summary_failures + 1)
                .returning(Article.summary_failures)
            ).scalar_one_or_none()
        if failures is not None and failures >= MAX_SUMMARY_FAILURES:
            log.warning("summarize_gave_up", article_id=article_id, failures=failures)
    except Exception:
        log.exception("summary_failure_record_failed", article_id=article_id)


def summarize_pending(client: SupportsLlm, limit: int = SUMMARY_BATCH_LIMIT) -> int:
    with session_scope() as session:
        ids = pending_summary_ids(session, limit)
    done = 0
    for article_id in ids:
        try:
            with session_scope() as session:
                article = session.get(Article, article_id)
                if article is None or article.summary_zh is not None:
                    continue
                summarize_article(session, client, article)
        except (LlmError, json.JSONDecodeError):
            # Content-level failures (truncation, bad JSON, empty summary)
            # count toward the give-up cap; transient transport or DB errors
            # do not, so an outage cannot blacklist articles.
            log.exception("summarize_failed", article_id=article_id)
            record_summary_failure(article_id)
        except Exception:
            log.exception("summarize_failed", article_id=article_id)
        else:
            done += 1
    return done


def embed_pending(client: SupportsLlm, limit: int = EMBED_BATCH_LIMIT) -> int:
    with session_scope() as session:
        ids = list(
            session.scalars(
                select(Article.id)
                .where(Article.summary_zh.is_not(None), Article.embedding.is_(None))
                .order_by(Article.id)
                .limit(limit)
            )
        )
    done = 0
    for batch_ids in batched(ids, EMBED_BATCH_SIZE):
        try:
            with session_scope() as session:
                articles = [
                    a
                    for article_id in batch_ids
                    if (a := session.get(Article, article_id)) is not None
                ]
                embed_articles(session, client, articles)
                done += len(articles)
        except Exception:
            log.exception("embed_batch_failed", article_ids=list(batch_ids))
    return done
