"""Current qualified content, independent of recommendation age and pool size."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Select, and_, func, or_, select, true
from sqlalchemy.orm import Session, aliased
from sqlalchemy.sql.selectable import Subquery

from unspun.core.config import get_settings
from unspun.core.content_reading import (
    CARD_VERSION,
    REVIEW_VERSION,
    CardDraft,
    ContentInput,
    card_valid,
    material_exclusion,
)
from unspun.core.models import Article, ContentDerivation, ContentMaterial, ContentObservation
from unspun.core.sources import Source
from unspun.pipeline.content_processing import content_input, processing_fingerprint


@dataclass
class Item:
    article: Article
    content: ContentInput
    row: ContentDerivation
    card: CardDraft
    channels: tuple[str, ...]
    qualification_versions: tuple[datetime, datetime]


def current_versions(
    *, preview: bool, as_of: datetime, sources: list[Source]
) -> Select[int, int, int, datetime, datetime]:
    """Reject historical/stale/unauthorized rows before applying a candidate bound."""
    features, admission = aliased(ContentDerivation), aliased(ContentDerivation)
    settings = get_settings()
    allowed = [
        and_(
            Article.source_id == source.id,
            true()
            if preview or source.r1.publish_scopes is None
            else ContentMaterial.scope.in_(source.r1.publish_scopes),
        )
        for source in sources
        if source.r1 and source.discovery_owner == "r1" and (preview or source.r1.publish)
    ]
    query = (
        select(
            Article.id.label("article_id"),
            ContentMaterial.id.label("material_id"),
            ContentDerivation.id.label("card_id"),
            features.updated_at.label("features_updated_at"),
            admission.updated_at.label("admission_updated_at"),
        )
        .select_from(Article)
        .join(
            ContentMaterial,
            and_(
                ContentMaterial.id == Article.current_material_id,
                ContentMaterial.article_id == Article.id,
            ),
        )
        .join(ContentDerivation, ContentDerivation.article_id == Article.id)
        .join(
            features,
            and_(
                features.article_id == Article.id,
                features.kind == "features",
                features.input_fingerprint == ContentDerivation.input_fingerprint,
            ),
        )
        .join(
            admission,
            and_(
                admission.article_id == Article.id,
                admission.kind == "admission",
                admission.input_fingerprint == ContentDerivation.input_fingerprint,
            ),
        )
        .where(
            Article.processing_track == "r1",
            Article.canonical_content_id.is_(None),
            or_(False, *allowed),
            ContentMaterial.scope != "none",
            ContentMaterial.access_status.in_(["ok", "restricted"]),
            ContentMaterial.metadata_fingerprint == Article.metadata_fingerprint,
            ContentDerivation.kind == "card",
        )
    )
    for member in (ContentDerivation, features, admission):
        query = query.where(
            member.material_id == ContentMaterial.id,
            member.metadata_fingerprint == Article.metadata_fingerprint,
            member.status == "ready",
            member.contract_version == CARD_VERSION,
            member.review_contract == REVIEW_VERSION,
            member.generation_model == settings.summary_model,
            member.review_model == settings.viewpoint_model,
            member.review_evidence.contains({"approved": True}),
            member.payload.contains({"include": True}),
            member.updated_at <= as_of,
        )
    return query


def qualified_items(session: Session, selected: Subquery) -> list[Item]:
    """Load the bounded versions in one statement and validate their actual inputs."""
    rows = session.execute(
        select(
            Article,
            ContentMaterial,
            ContentDerivation,
            selected.c.features_updated_at,
            selected.c.admission_updated_at,
        )
        .select_from(Article)
        .join(selected, selected.c.article_id == Article.id)
        .join(ContentMaterial, ContentMaterial.id == selected.c.material_id)
        .join(ContentDerivation, ContentDerivation.id == selected.c.card_id)
        .order_by(Article.id)
        .execution_options(populate_existing=True)
    )
    result: list[Item] = []
    for article, material, row, features_at, admission_at in rows:
        try:
            content = content_input(article, material)
            if row.input_fingerprint != processing_fingerprint(content, "card"):
                continue
            card = CardDraft.model_validate(
                {
                    key: value
                    for key, value in (row.payload or {}).items()
                    if key in CardDraft.model_fields
                }
            )
            if not card.include or not card_valid(card, content) or material_exclusion(content):
                continue
            result.append(Item(article, content, row, card, (), (features_at, admission_at)))
        except (ValueError, KeyError, TypeError):
            # Poisoned/stale input never falls back to a previous result or legacy text.
            continue
    if result:
        identities = [item.article.id for item in result]
        channels: dict[int, set[str]] = {
            item.article.id: {item.article.source_id} for item in result
        }
        for identity, source in session.execute(
            select(
                func.coalesce(Article.canonical_content_id, Article.id),
                ContentObservation.source_id,
            )
            .join(ContentObservation, ContentObservation.article_id == Article.id)
            .where(func.coalesce(Article.canonical_content_id, Article.id).in_(identities))
            .distinct()
        ):
            channels[identity].add(source)
        for item in result:
            item.channels = tuple(sorted(channels[item.article.id]))
    return result


def qualified_item(
    session: Session, article_id: int, *, preview: bool, as_of: datetime, sources: list[Source]
) -> Item | None:
    versions = current_versions(preview=preview, as_of=as_of, sources=sources).where(
        Article.id == article_id
    )
    items = qualified_items(session, versions.subquery())
    return next(iter(items), None)
