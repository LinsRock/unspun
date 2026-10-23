"""Bounded independent recall lanes, sharing current content and R2-07 publication gates."""

import re
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import (
    DateTime,
    Select,
    Text,
    and_,
    case,
    cast,
    func,
    literal,
    literal_column,
    or_,
    select,
)
from sqlalchemy.dialects.postgresql import JSONPATH, distinct_on
from sqlalchemy.orm import Session, aliased

from unspun.core.config import get_settings
from unspun.core.content import fingerprint
from unspun.core.content_feed import (
    candidate_versions,
    item_out,
    normalized,
    rank,
    rules,
    term_matches,
)
from unspun.core.content_publication import current_versions, qualified_items
from unspun.core.content_reading import cheap_exclusion, current_value
from unspun.core.hybrid_contracts import HybridRules, Signal
from unspun.core.hybrid_ranking import Candidate, time_key, topic_preference_score
from unspun.core.models import Article, ContentDerivation, ContentMaterial, ContentObservation
from unspun.core.reader_models import ContentFeedback, ReaderInterest, TopicPreference
from unspun.core.sources import Source
from unspun.core.synthesis_models import TopicSynthesis
from unspun.core.topic_models import Topic, TopicMember, TopicUpdate
from unspun.core.topic_synthesis import qualified_topic_text
from unspun.core.topics import topic_snapshot


def feedback_rows() -> Any:
    """Resolve retained feedback aliases in SQL; load only bounded candidate feedback.

    Highest (version, original ID) wins exactly as in Reader.effective_feedback.
    Cyclic, missing or non-R1 identities cannot supply a recall or ranking signal.
    """
    identity = (
        select(
            ContentFeedback.article_id.label("feedback_id"),
            Article.id.label("root_id"),
            Article.canonical_content_id.label("next_id"),
            literal(0).label("depth"),
        )
        .join(Article, Article.id == ContentFeedback.article_id)
        .where(Article.processing_track == "r1")
        .cte("feedback_identity", recursive=True)
    )
    parent = aliased(Article)
    identity = identity.union_all(
        select(
            identity.c.feedback_id,
            parent.id,
            parent.canonical_content_id,
            identity.c.depth + 1,
        )
        .join(parent, parent.id == identity.c.next_id)
        .where(identity.c.depth < 63, parent.processing_track == "r1")
    )
    ranked = (
        select(
            identity.c.root_id,
            ContentFeedback.value,
            func.row_number()
            .over(
                partition_by=identity.c.root_id,
                order_by=(ContentFeedback.version.desc(), ContentFeedback.article_id.desc()),
            )
            .label("position"),
        )
        .join(ContentFeedback, ContentFeedback.article_id == identity.c.feedback_id)
        .where(identity.c.next_id.is_(None))
        .subquery()
    )
    return select(ranked.c.root_id, ranked.c.value).where(ranked.c.position == 1).subquery()


def _term(expression: Any, value: str) -> Any:
    term = normalized(value)
    normalized_text = func.lower(func.normalize(cast(expression, Text), literal_column("NFKC")))
    if term.isascii() and any(c.isalnum() for c in term):
        return normalized_text.op("~")("(^|[^a-z0-9_])" + re.escape(term) + "($|[^a-z0-9_])")
    return normalized_text.contains(term, autoescape=True)


def interest_condition(interests: list[ReaderInterest], positive: Any) -> Any:
    conditions: list[Any] = [Article.id.in_(positive)]
    for interest in interests:
        target, kind = interest.target, interest.kind
        value = target["value"]
        if kind == "domain":
            conditions.append(ContentDerivation.payload["domains"].contains([value]))
        elif kind == "source":
            conditions.append(
                or_(
                    Article.source_id == value,
                    Article.id.in_(
                        select(func.coalesce(Article.canonical_content_id, Article.id))
                        .join(ContentObservation, ContentObservation.article_id == Article.id)
                        .where(ContentObservation.source_id == value)
                    ),
                )
            )
        elif kind == "term":
            conditions.append(
                or_(
                    _term(func.coalesce(Article.r1_metadata["title"].astext, Article.title), value),
                    _term(
                        func.jsonb_path_query_array(
                            ContentMaterial.paragraphs, cast("$[*].text", JSONPATH)
                        ),
                        value,
                    ),
                )
            )
        elif kind == "author":
            authors = (
                func.jsonb_array_elements(Article.r1_metadata["authors"])
                .table_valued("value")
                .alias()
            )
            author = authors.c.value
            platform = func.coalesce(
                author.op("->>")("platform"), Article.r1_metadata["platform"].astext, ""
            )
            field = author.op("->>")("platform_id" if target.get("author_id") else "name")
            match = (
                field == target["author_id"]
                if target.get("author_id")
                else func.lower(func.normalize(field, literal_column("NFKC"))) == normalized(value)
            )
            conditions.append(
                select(literal(1))
                .select_from(authors)
                .where(
                    match,
                    func.lower(func.normalize(platform, literal_column("NFKC")))
                    == normalized(target.get("platform") or ""),
                )
                .exists()
            )
    return or_(False, *conditions)


def content_candidates(
    session: Session,
    sources: list[Source],
    policy: HybridRules,
    interests: list[ReaderInterest],
    now: datetime,
    as_of: datetime,
) -> tuple[list[Candidate], dict[str, int], str]:
    effective = feedback_rows()
    positive = select(effective.c.root_id).where(effective.c.value == "interested")
    signals = [s for s in policy.signals if s.type == "content" and s.current(now)]
    conditions = {
        "important": Article.id.in_(
            [int(s.target_id) for s in signals if s.kind == "important" and s.target_id.isdecimal()]
        ),
        "interest": interest_condition(interests, positive),
        "public_attention": Article.id.in_(
            [
                int(s.target_id)
                for s in signals
                if s.kind == "public_attention" and s.target_id.isdecimal()
            ]
        ),
        "readable": literal(True),
    }
    lane_queries: list[Select[Any, Any]] = []
    for lane, condition in conditions.items():
        selected = candidate_versions(
            preview=False,
            as_of=now,
            sources=sources,
            bound=policy.readable_limit if lane == "readable" else policy.content_lane_limit,
            condition=condition,
        ).subquery()
        lane_queries.append(select(selected.c.article_id, literal(lane).label("lane")))
    lanes: dict[int, set[str]] = {}
    counts = dict.fromkeys(conditions, 0)
    for identity, lane in session.execute(lane_queries[0].union_all(*lane_queries[1:])):
        lanes.setdefault(identity, set()).add(lane)
        counts[lane] += 1
    selected = current_versions(preview=False, as_of=now, sources=sources).where(
        Article.id.in_(lanes)
    )
    items = [
        i
        for i in qualified_items(session, selected.subquery())
        if not cheap_exclusion(i.content, now)
        and current_value(i.content, i.card.genre, now)[1] != "outside_current_window"
    ]
    feedback = {
        int(row[0]): str(row[1])
        for row in session.execute(
            select(effective.c.root_id, effective.c.value).where(
                effective.c.root_id.in_([i.article.id for i in items])
            )
        )
    }
    scored, reader_snapshot = rank(
        session, items, as_of, "latest", rules(), feedback_values=feedback
    )
    candidates: list[Candidate] = []
    for item, reasons in scored:
        payload = item_out(item, reasons, sources)
        times = [
            t
            for t in item.content.metadata.times
            if t.kind in {"original", "editorial", "question_created"}
        ]
        stamp = next((t for t in times if t.kind == "original"), next(iter(times), None))
        version = fingerprint(
            [
                item.content.model_dump(mode="json"),
                item.row.payload,
                item.row.input_fingerprint,
                item.row.updated_at.isoformat(),
                [v.isoformat() for v in item.qualification_versions],
                item.channels,
            ]
        )
        c = Candidate(
            "content",
            str(item.article.id),
            version,
            item.card.title_zh,
            item.channels,
            item.card.domains,
            stamp.model_dump(mode="json")
            if stamp
            else {"kind": "original", "precision": "unknown"},
            payload,
            reasons,
            protect=item.card.genre in {"analysis", "opinion", "knowledge", "review"}
            or item.content.metadata.genre == "experience",
        )
        attach_signals(c, signals, now, [item.content.model_dump(mode="json")])
        actual = lanes[item.article.id] - {"important", "public_attention", "interest"}
        actual.update(c.signals)
        if reasons["interest"] > 0 or reasons["feedback_value"] == "interested":
            actual.add("interest")
        c.lanes = tuple(sorted(actual))
        if c.lanes:
            candidates.append(c)
    return candidates, counts, reader_snapshot


def attach_signals(
    c: Candidate, signals: list[Signal], now: datetime, materials: list[dict[str, Any]]
) -> None:
    for signal in signals:
        if (signal.type, signal.target_id, signal.target_version) != (
            c.type,
            c.id,
            c.version,
        ) or not signal.current(now):
            continue
        valid = True
        for ref in signal.evidence:
            material = next(
                (
                    m
                    for m in materials
                    if m["article_id"] == ref.article_id and m["material_id"] == ref.material_id
                ),
                None,
            )
            if material is None or ref.paragraph >= len(material["paragraphs"]):
                valid = False
                break
            if ref.quote not in material["paragraphs"][ref.paragraph]["text"]:
                valid = False
                break
        if valid:
            c.signals[signal.kind] = signal


def _stamp(expression: Any) -> Any:
    at, on = expression["at"].astext, expression["on"].astext
    return case(
        (func.pg_input_is_valid(at, "timestamp with time zone"), cast(at, DateTime(timezone=True))),
        (
            and_(at.is_(None), func.pg_input_is_valid(on, "date")),
            func.timezone("Asia/Shanghai", cast(on, DateTime())),
        ),
        else_=None,
    )


def topic_candidates(
    session: Session,
    sources: list[Source],
    policy: HybridRules,
    interests: list[ReaderInterest],
    now: datetime,
) -> tuple[list[Candidate], dict[str, int]]:
    # Only current revisions are loaded. Historical synthesis/update payloads stay in SQL.
    latest = (
        select(TopicSynthesis)
        .ext(distinct_on(TopicSynthesis.topic_id))
        .order_by(
            TopicSynthesis.topic_id, TopicSynthesis.created_at.desc(), TopicSynthesis.task_id.desc()
        )
        .subquery()
    )
    updates = (
        select(TopicUpdate)
        .ext(distinct_on(TopicUpdate.topic_id, TopicUpdate.update_id))
        .order_by(TopicUpdate.topic_id, TopicUpdate.update_id, TopicUpdate.revision.desc())
        .subquery()
    )
    progress = (
        select(
            updates.c.topic_id,
            func.count().label("size"),
            func.max(
                func.coalesce(
                    _stamp(updates.c.payload["occurred"]), _stamp(updates.c.payload["reported"])
                )
            )
            .filter(updates.c.status == "active")
            .label("at"),
        )
        .group_by(updates.c.topic_id)
        .subquery()
    )
    members = (
        select(TopicMember.topic_id, func.count().label("size"))
        .where(TopicMember.active)
        .group_by(TopicMember.topic_id)
        .subquery()
    )
    signals = [s for s in policy.signals if s.type == "topic" and s.current(now)]
    interest_filters = [
        Topic.domains.contains([i.target["value"]])
        if i.kind == "domain"
        else _term(Topic.title, i.target["value"])
        for i in interests
        if i.kind in {"domain", "term"}
    ]
    preferences_enabled = get_settings().r2_topic_preferences_enabled
    if preferences_enabled:
        interest_filters.append(
            Topic.id.in_(
                select(TopicPreference.topic_id).where(
                    or_(TopicPreference.followed, TopicPreference.feedback == "interested")
                )
            )
        )
    conditions = {
        "important": Topic.id.in_([s.target_id for s in signals if s.kind == "important"]),
        "interest": or_(False, *interest_filters),
        "public_attention": Topic.id.in_(
            [s.target_id for s in signals if s.kind == "public_attention"]
        ),
        "readable": literal(True),
    }
    queries: list[Select[Any, Any]] = []
    for lane, condition in conditions.items():
        pool = (
            select(
                Topic.id,
                progress.c.at,
                func.row_number()
                .over(
                    partition_by=Topic.domains[0].astext,
                    order_by=(progress.c.at.desc().nulls_last(), Topic.id),
                )
                .label("position"),
            )
            .join(latest, latest.c.topic_id == Topic.id)
            .join(members, members.c.topic_id == Topic.id)
            .outerjoin(progress, progress.c.topic_id == Topic.id)
            .where(
                Topic.status == "active",
                latest.c.status == "applied",
                latest.c.response_mode == "live",
                members.c.size <= policy.topic_member_limit,
                func.coalesce(progress.c.size, 0) <= policy.topic_update_limit,
                or_(progress.c.at.is_(None), progress.c.at >= now - timedelta(days=14)),
                condition,
            )
            .subquery()
        )
        bounded = (
            select(pool)
            .order_by(pool.c.position, pool.c.at.desc().nulls_last(), pool.c.id)
            .limit(policy.topic_lane_limit)
            .subquery()
        )
        queries.append(select(bounded.c.id, literal(lane).label("lane")))
    lanes: dict[str, set[str]] = {}
    counts = dict.fromkeys(conditions, 0)
    for identity, lane in session.execute(queries[0].union_all(*queries[1:])):
        lanes.setdefault(identity, set()).add(lane)
        counts[lane] += 1
    result: list[Candidate] = []
    for identity in sorted(lanes):
        try:
            view = qualified_topic_text(session, UUID(identity), sources=sources, now=now)
            if view is None:
                continue
            topic = session.get(Topic, identity, populate_existing=True)
            synthesis = session.get(TopicSynthesis, view["version"])
            assert topic and synthesis
            snapshot = topic_snapshot(session, topic, sources, now)
            stamps: list[dict[str, Any]] = []
            for update in snapshot["updates"]:
                if not update["check"]["valid"]:
                    continue
                payload = update["row"]["payload"]
                if payload.get("classification") not in {"development", "discussion_focus"}:
                    continue
                kind = "occurred" if payload["occurred"]["precision"] != "unknown" else "reported"
                stamps.append(
                    {**payload[kind], "kind": kind, "progress_key": payload["progress_key"]}
                )
            stamp = (
                max(stamps, key=time_key)
                if stamps
                else {"kind": "occurred", "precision": "unknown"}
            )
            if stamp["precision"] != "unknown" and time_key(stamp) < now - timedelta(days=14):
                continue
            matched = [
                i
                for i in interests
                if (i.kind == "domain" and i.target["value"] in topic.domains)
                or (i.kind == "term" and term_matches(i.target["value"], topic.title))
            ]
            reader = rules()
            interest = min(
                reader.interest_cap, sum(reader.interest_weights.get(i.kind, 0) for i in matched)
            )
            preference = session.get(TopicPreference, identity) if preferences_enabled else None
            direct = (
                topic_preference_score(
                    preference.followed if preference else False,
                    preference.feedback if preference else None,
                    policy,
                    reader,
                )
                if preferences_enabled
                else {}
            )
            version = fingerprint([view, snapshot, topic.revision])
            protected = {
                str(m["article_id"])
                for m in snapshot["members"]
                if m["relation"] in {"opinion", "explanation"}
            }
            duplicates = {
                str(m["article_id"]) for m in snapshot["members"] if m["relation"] == "reprint"
            }
            nonduplicates: set[str] = set()
            for contribution in synthesis.draft["contributions"]:
                identities = {str(r["article_id"]) for r in contribution["evidence"]}
                if contribution["classification"] == "duplicate" and len(identities) == 1:
                    duplicates.update(identities)
                elif contribution["classification"] != "duplicate":
                    nonduplicates.update(identities)
            duplicates.difference_update(nonduplicates)
            c = Candidate(
                "topic",
                identity,
                version,
                topic.title,
                tuple(sorted({m["source_id"] for m in view["material_scope"]})),
                tuple(topic.domains),
                stamp,
                {
                    **view,
                    "material_scope": [
                        {
                            k: m[k]
                            for k in ("article_id", "material_id", "source_id", "scope", "metadata")
                        }
                        for m in view["material_scope"]
                    ],
                    "revision": topic.revision,
                    "members": [
                        {k: m[k] for k in ("article_id", "material_id", "relation", "revision")}
                        for m in snapshot["members"]
                    ],
                },
                {
                    "reading_value": None,
                    "current_value": None,
                    "interest": interest,
                    "feedback": None,
                    "matched_interests": [i.resource_key for i in matched],
                    **direct,
                    "score": interest + direct.get("topic_preference_score", 0),
                },
                duplicate_ids=tuple(sorted(duplicates - protected)),
                unique_ids=tuple(sorted(protected)),
            )
            attach_signals(c, signals, now, view["material_scope"])
            actual = lanes[identity] - {"important", "public_attention", "interest"}
            actual.update(c.signals)
            if interest or (
                preference and (preference.followed or preference.feedback == "interested")
            ):
                actual.add("interest")
            c.lanes = tuple(sorted(actual))
            if c.lanes:
                result.append(c)
        except (ValueError, KeyError, TypeError):
            # An invalid dependency never falls back to earlier topic text.
            continue
    return result, counts
