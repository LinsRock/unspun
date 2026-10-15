"""Versioned publication contract, independent of importance and source reputation.

Only reviewed Chinese facts with matching source quotes can reach the reading
projection. Its input hash prevents stale projections surviving source edits.
"""

import hashlib
import re
from typing import Any, cast

from sqlalchemy import ColumnElement, and_, case, func, literal, select
from sqlalchemy.orm import Session

from unspun.core.grounding import (
    SUMMARY_VERSION,
    article_source_text,
    normalize_text,
    quote_in_source,
)
from unspun.core.models import Article, Event

READING_VERSION = "reading-v1"


def input_hash(article: Article) -> str:
    return hashlib.md5(f"{article.title}\n{article.content or ''}".encode()).hexdigest()


def chinese_text(value: str | None) -> bool:
    if not value:
        return False
    han = len(re.findall(r"[\u3400-\u9fff]", value))
    words = len(re.findall(r"[a-zA-Z]+", value))
    # Count Latin words rather than letters so names and acronyms are allowed.
    return (
        han >= 2
        and han >= words
        and not any(
            len(re.findall(r"[a-zA-Z]+", sentence)) >= 10
            and not re.search(r"[\u3400-\u9fff]", sentence)
            for sentence in re.split(r"[.!?\n\u3002\uff01\uff1f]", value)
        )
    )


def fact_key(value: str) -> str:
    # Preserve numeric punctuation: 1.2 must not collapse into 12, nor -1 into 1.
    return re.sub(
        r"[\s\u3002\uff0c,\u3001\uff1b;\uff01!\uff1f?\uff1a:\u201c\u201d\"\u2018\u2019]+",
        "",
        normalize_text(value).casefold(),
    ).rstrip(".")


def reading_projection(article: Article) -> dict[str, Any]:
    grounding = article.summary_grounding or {}
    result: dict[str, Any] = {
        "version": READING_VERSION,
        "input_hash": input_hash(article),
        "status": "withheld",
        "kind": "lead",
        "reason": "review_pending",
        "facts": [],
    }
    if grounding.get("status") == "review_limited":
        result["reason"] = "review_budget"
        return result
    if grounding.get("verification", {}).get("method") != "source_entailment_review":
        return result
    if not grounding.get("title_verified"):
        result["reason"] = "title_unverified"
        return result
    if not chinese_text(article.title_zh):
        result["reason"] = "language_invalid"
        return result
    seen = {fact_key(article.title_zh or "")}
    facts: list[dict[str, str]] = []
    for fact in grounding.get("facts", []):
        if not isinstance(fact, dict):
            continue
        fact = cast(dict[str, Any], fact)
        text, quote = fact.get("text"), fact.get("quote")
        if not isinstance(text, str) or not isinstance(quote, str):
            continue
        if not chinese_text(text):
            result["reason"] = "language_invalid"
            return result
        key = fact_key(text)
        if (
            key in seen
            or quote_in_source(quote, article.title)
            or not quote.strip()
            or not quote_in_source(quote, article_source_text(article))
        ):
            continue
        seen.add(key)
        facts.append({"text": text, "quote": quote})
    if not facts:
        result["reason"] = "no_added_facts"
        return result
    detailed = (
        grounding.get("status") == "grounded"
        and len(facts) >= 2
        and len(re.findall(r"[\u3400-\u9fff]", "".join(f["text"] for f in facts))) >= 60
    )
    result.update(
        status="ready",
        kind="report" if detailed else "brief",
        reason=None,
        title=article.title_zh,
        facts=facts,
    )
    return result


def attach_reading(article: Article) -> None:
    article.summary_grounding = {
        **(article.summary_grounding or {}),
        "reading": reading_projection(article),
    }


def input_hash_expression() -> ColumnElement[str]:
    return func.md5(Article.title + literal("\n") + func.coalesce(Article.content, ""))


def ready_condition() -> ColumnElement[bool]:
    reading = Article.summary_grounding["reading"]
    return and_(
        reading["version"].astext == READING_VERSION,
        reading["status"].astext == "ready",
        reading["input_hash"].astext == input_hash_expression(),
    )


def current_reading(article: Article) -> dict[str, Any]:
    stored = (article.summary_grounding or {}).get("reading", {})
    if stored.get("version") == READING_VERSION and stored.get("input_hash") == input_hash(article):
        return stored
    reason = (
        "review_budget"
        if (article.summary_grounding or {}).get("status") == "review_limited"
        else "review_pending"
    )
    return {"status": "withheld", "kind": "lead", "reason": reason, "facts": []}


def event_reading(articles: list[Article]) -> dict[str, Any]:
    ready = [
        (a, current_reading(a)) for a in articles if current_reading(a).get("status") == "ready"
    ]
    if not ready:
        return {"status": "withheld", "kind": "lead", "title": None, "facts": [], "article_ids": []}
    # Richest reviewed material leads; stable ID breaks ties, not arrival time.
    ready.sort(key=lambda pair: (-len(pair[1]["facts"]), pair[0].id))
    lead, lead_projection = ready[0]
    title = lead_projection["title"]
    title_keys = {fact_key(lead.title), fact_key(title)}
    anchor_keys = {
        fact_key(f["text"]) for f in lead_projection["facts"] if len(fact_key(f["text"])) >= 16
    }
    # Clustering is a candidate relation, not a license to combine unrelated facts.
    # Keep other materials as links unless a concrete reviewed anchor is shared.
    ready = [
        (a, p)
        for a, p in ready
        if a.id == lead.id
        or (
            any(
                len(key) >= 8 and key in title_keys
                for key in (fact_key(a.title), fact_key(p["title"]))
            )
            or any(fact_key(f["text"]) in anchor_keys for f in p["facts"])
        )
    ]
    seen = {fact_key(title)}
    facts: list[dict[str, Any]] = []
    for article, projection in ready:
        for fact in projection["facts"]:
            key = fact_key(fact["text"])
            if key in seen:
                continue
            seen.add(key)
            facts.append({**fact, "article_id": article.id})
    return {
        "status": "ready",
        "title": title,
        "facts": facts[:8],
        "kind": "aggregation"
        if len({f["article_id"] for f in facts[:8]}) >= 2
        else ready[0][1]["kind"],
        "article_ids": [a.id for a, _ in ready],
    }


def publication_counts(session: Session) -> dict[str, int]:
    reason = case(
        (ready_condition(), "ready"),
        (Article.summary_grounding["status"].astext == "review_limited", "review_budget"),
        else_=func.coalesce(
            Article.summary_grounding["reading"]["reason"].astext, "review_pending"
        ),
    )
    return {
        key: count for key, count in session.execute(select(reason, func.count()).group_by(reason))
    }


def refresh_event_text(event: Event) -> bool:
    reading = event_reading(list(event.articles))
    if reading["status"] != "ready":
        return False
    title = reading["title"]
    summary = " ".join(fact["text"] for fact in reading["facts"])
    if event.title == title and event.summary_zh == summary:
        return False
    event.title, event.summary_zh = title, summary
    return True


def hydrate_legacy_reading(article: Article) -> bool:
    """Recover a provable v5 title verdict, without inventing a review.

    v5 selected title_zh ONLY from supported title facts or the exact raw title.
    Thus a different Chinese translation under its semantic-review method has
    passed review. An identical title is ambiguous and stays queued for review.
    This rule is intentionally restricted to the audited v5 implementation.
    """
    grounding = article.summary_grounding or {}
    if (
        grounding.get("reading")
        or grounding.get("version") != SUMMARY_VERSION
        or grounding.get("status") not in {"grounded", "limited"}
        or grounding.get("verification", {}).get("method") != "source_entailment_review"
        or not article.title_zh
        or article.title_zh == article.title
    ):
        return False
    article.summary_grounding = {
        **grounding,
        "title_verified": True,
        "title_verification_basis": "v5_supported_translation_branch",
    }
    attach_reading(article)
    return True
