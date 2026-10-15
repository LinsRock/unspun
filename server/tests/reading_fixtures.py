"""Explicit reviewed Chinese material for publication integration tests."""

from unspun.core.models import Article, Event
from unspun.core.reading import attach_reading


def approve(article: Article) -> None:
    article.title_zh = "\u6d4b\u8bd5\u62a5\u9053\u5171\u540c\u4e8b\u4ef6\u6807\u9898"
    article.content = "The team launched two satellites and completed the first orbit."
    article.summary_zh = (
        "\u56e2\u961f\u53d1\u5c04\u4e24\u9897\u536b\u661f\u5b8c\u6210\u7ed5\u8f68\u3002"
    )
    article.summary_grounding = {
        "status": "grounded",
        "title_verified": True,
        "facts": [{"text": article.summary_zh, "quote": article.content}],
        "verification": {"method": "source_entailment_review"},
    }
    attach_reading(article)


def approve_event(event: "Event") -> None:
    if not event.articles:
        event.articles.append(
            Article(
                source_id="bbc-world",
                title="Original source",
                url=f"https://test/event/{event.id}",
                fetched_at=event.first_seen_at,
            )
        )
    for article in event.articles:
        approve(article)
