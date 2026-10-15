"""Daily digest snapshots; the LLM writes only an introduction to existing events."""

import json
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from pydantic import BaseModel
from sqlalchemy import Float, func, literal, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, selectinload

from unspun.api.events import LN2, EventOut, event_out
from unspun.core.config import get_settings
from unspun.core.db import session_scope
from unspun.core.llm import LlmClient, SupportsLlm
from unspun.core.logging import get_logger
from unspun.core.models import Article, Digest, Event
from unspun.core.params import DigestParams, get_scoring_params
from unspun.core.reading import chinese_text, ready_condition
from unspun.core.sources import load_sources

log = get_logger("unspun.pipeline.digest")
WINDOW_HOURS = 24
EMPTY_INTRO = (
    "\u8fc7\u53bb 24 \u5c0f\u65f6\u6682\u65e0\u53ef\u751f\u6210\u65e5\u62a5\u7684\u4e8b\u4ef6\u3002"
)
DIGEST_SYSTEM = (
    "Write one short paragraph in Simplified Chinese as a daily news digest introduction. "
    "Use only the supplied event titles and summaries. Do not invent facts, sources, "
    'or claims of completeness. Return a JSON object with exactly one field: {"intro": "..."}.'
)


class DigestPayload(BaseModel):
    intro: str
    window_start: datetime
    window_end: datetime
    timezone: str
    events: list[EventOut]


def due_report_date(now: datetime, params: DigestParams) -> date | None:
    local = now.astimezone(ZoneInfo(params.digest_timezone))
    return local.date() if local.hour >= params.digest_hour else None


def select_digest_events(
    session: Session,
    now: datetime,
    *,
    top_n: int,
    half_life_hours: float,
) -> list[tuple[Event, float]]:
    age_hours = func.cast(func.extract("epoch", literal(now) - Event.changed_at), Float) / 3600
    decayed = Event.score_final * func.exp(-LN2 * age_hours / half_life_hours)
    rows = session.execute(
        select(Event, decayed)
        .where(
            Event.changed_at >= now - timedelta(hours=WINDOW_HOURS),
            Event.changed_at <= now,
            Event.score_final.is_not(None),
            select(Article.id).where(Article.event_id == Event.id, ready_condition()).exists(),
            Event.summary_zh.is_not(None),
            func.length(func.trim(Event.summary_zh)) > 0,
        )
        .options(selectinload(Event.articles), selectinload(Event.viewpoint))
        .order_by(decayed.desc(), Event.changed_at.desc(), Event.id.asc())
        .limit(top_n)
    ).all()
    return [(event, float(score)) for event, score in rows]


def generate_digest(
    session: Session,
    client: SupportsLlm | None,
    report_date: date,
    now: datetime,
    params: DigestParams,
    half_life_hours: float,
) -> bool:
    """Replace one daily snapshot, returning False on LLM failure without losing usage.

    The caller commits the session even on rejection, so usage rows recorded
    before a parse failure survive. Existing snapshots are changed only after
    all generation and validation succeeds.
    """
    rows = select_digest_events(session, now, top_n=params.top_n, half_life_hours=half_life_hours)
    names = {s.id: s.name for s in load_sources()}
    events = [event_out(event, score, names, published=True) for event, score in rows]
    intro = EMPTY_INTRO
    if events:
        if client is None:
            log.warning("digest_skipped", reason="UNSPUN_OPENROUTER_API_KEY not set")
            return False
        try:
            out = client.chat_json(
                session,
                model=get_settings().digest_model,
                system=DIGEST_SYSTEM,
                user=json.dumps(
                    {
                        "report_date": report_date.isoformat(),
                        "events": [{"title": e.title, "summary_zh": e.summary_zh} for e in events],
                    },
                    ensure_ascii=False,
                ),
                purpose="digest",
                max_tokens=1024,
            )
            raw_intro = out.get("intro")
            if not isinstance(raw_intro, str) or not chinese_text(raw_intro):
                raise ValueError("digest intro must be readable Chinese")
            intro = raw_intro.strip()
        except Exception as exc:
            log.warning("digest_generation_failed", report_date=str(report_date), error=str(exc))
            return False
    payload = DigestPayload(
        intro=intro,
        window_start=now - timedelta(hours=WINDOW_HOURS),
        window_end=now,
        timezone=params.digest_timezone,
        events=events,
    ).model_dump(mode="json")
    statement = (
        insert(Digest)
        .values(
            report_date=report_date,
            kind="daily",
            payload=payload,
            generated_at=now,
        )
        .on_conflict_do_update(
            constraint="uq_digests_report_date_kind",
            set_={"payload": payload, "generated_at": now},
        )
        .returning(Digest)
    )
    session.scalars(statement, execution_options={"populate_existing": True}).one()
    log.info("digest_generated", report_date=str(report_date), events=len(events))
    return True


def digest_pending(now: datetime | None = None) -> bool:
    """Generate today's missing digest at/after the configured local hour."""
    now = now or datetime.now(UTC)
    config = get_scoring_params()
    report_date = due_report_date(now, config.digest)
    if report_date is None:
        return False
    with session_scope() as session:
        if (
            session.scalar(
                select(Digest.id).where(
                    Digest.report_date == report_date,
                    Digest.kind == "daily",
                )
            )
            is not None
        ):
            return False
        # Empty digests can be generated without credentials. A configured
        # client is opened only after the already-generated check.
        if not get_settings().openrouter_api_key:
            return generate_digest(
                session, None, report_date, now, config.digest, config.stream.half_life_hours
            )
        with LlmClient() as client:
            return generate_digest(
                session, client, report_date, now, config.digest, config.stream.half_life_hours
            )
