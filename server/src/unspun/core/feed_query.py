# ruff: noqa: E501
"""PostgreSQL original-publication feed ordering and bounded keyset cursors."""

import base64
import hashlib
import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from typing import Any, cast
from zoneinfo import ZoneInfo

import yaml
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from unspun.core.config import get_settings

RANKING_VERSION = "original-impact-v1-24h-6h-0.5"


def publisher_aliases() -> tuple[dict[str, str], str]:
    path = Path(get_settings().config_dir) / "media_groups.yml"
    raw = path.read_bytes()
    document = yaml.safe_load(raw)
    aliases = cast(dict[str, str], document["aliases"])
    return aliases, RANKING_VERSION + "-" + hashlib.sha256(raw).hexdigest()[:12]


def window_start(period: str, as_of: datetime) -> datetime | None:
    if period == "all":
        return None
    if period == "today":
        local = as_of.astimezone(ZoneInfo("Asia/Shanghai"))
        return datetime.combine(local.date(), time(), tzinfo=local.tzinfo).astimezone(UTC)
    return as_of - timedelta(hours=24 if period == "24h" else 168)


@dataclass
class FeedPage:
    rows: list[dict[str, Any]]
    as_of: datetime
    next_cursor: str | None
    start: datetime | None
    version: str


def decode_cursor(
    value: str, sort: str, period: str, now: datetime, unread_only: bool = False
) -> dict[str, Any]:
    try:
        if len(value) > 2048:
            raise ValueError()
        payload: Any = json.loads(
            base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
        )
        if not isinstance(payload, dict):
            raise ValueError()
        payload = cast(dict[str, Any], payload)
        if set(payload) != {
            "v",
            "sort",
            "range",
            "as_of",
            "key",
            "generation",
            "unread_only",
        }:
            raise ValueError()
        if (
            payload["v"] != publisher_aliases()[1]
            or payload["sort"] != sort
            or payload["range"] != period
            or type(payload["unread_only"]) is not bool
            or payload["unread_only"] != unread_only
        ):
            raise ValueError()
        payload = cast(dict[str, Any], payload)
        as_of = datetime.fromisoformat(payload["as_of"])
        if as_of.utcoffset() is None or as_of > now or as_of < datetime(1970, 1, 1, tzinfo=UTC):
            raise ValueError()
        raw_key: Any = payload["key"]
        if not isinstance(raw_key, list):
            raise ValueError()
        key = cast(list[Any], raw_key)
        if len(key) != 5 or any(type(k) not in (int, float) or not math.isfinite(k) for k in key):
            raise ValueError()
        if key[0] not in (0, 1) or key[1] not in (0, 1) or type(key[4]) is not int or key[4] < 1:
            raise ValueError()
        if (
            any(abs(k) > 1e12 for k in key)
            or not isinstance(payload["generation"], str)
            or len(payload["generation"]) != 32
        ):
            raise ValueError()
        payload["as_of"] = as_of.astimezone(UTC)
        return payload
    except (ValueError, TypeError, KeyError, OverflowError):
        raise HTTPException(400, "Invalid feed cursor") from None


# Bounds match core.publication: date-only UTC+14 lower, UTC-12 upper;
# the lower is an ordering anchor, never a user-visible publication instant.
_SQL = r"""
WITH visible AS (
 SELECT a.*, CASE WHEN reported_precision='time' THEN reported_at
 WHEN reported_precision='date' THEN CASE WHEN reported_date >= date '1970-01-01' THEN greatest((reported_date::timestamp AT TIME ZONE 'UTC') - interval '14 hours', timestamptz '1970-01-01') END END AS raw_lower,
 CASE WHEN reported_precision='time' THEN reported_at
 WHEN reported_precision='date' THEN least((reported_date::timestamp AT TIME ZONE 'UTC') + interval '36 hours', fetched_at + interval '5 minutes', :as_of) END AS raw_upper
 FROM articles a WHERE fetched_at <= :as_of AND event_id IS NOT NULL
), bounded AS (
 SELECT *, CASE WHEN raw_lower >= timestamptz '1970-01-01' AND raw_lower <= raw_upper AND raw_lower <= :as_of AND raw_lower <= fetched_at + interval '5 minutes' THEN raw_lower END AS lower_bound
 FROM visible
), times AS (
 SELECT event_id, min(lower_bound) AS earliest_lower, max(lower_bound) AS latest_lower,
 count(lower_bound)::int AS valid_time_count,
 count(*) FILTER (WHERE reported_precision='unknown' OR (reported_precision='time' AND reported_at IS NULL) OR (reported_precision='date' AND reported_date IS NULL))::int AS missing_time_count,
 (count(*) - count(lower_bound) - count(*) FILTER (WHERE reported_precision='unknown' OR (reported_precision='time' AND reported_at IS NULL) OR (reported_precision='date' AND reported_date IS NULL)))::int AS invalid_time_count
 FROM bounded GROUP BY event_id
), groups AS (
 SELECT event_id, coalesce(CAST(:aliases AS jsonb)->>publisher_group, publisher_group, 'source:' || source_id) AS publisher, min(lower_bound) AS first_original
 FROM bounded WHERE lower_bound IS NOT NULL GROUP BY event_id, coalesce(CAST(:aliases AS jsonb)->>publisher_group, publisher_group, 'source:' || source_id)
), heat AS (
 SELECT event_id, count(*)::int AS active_publishers,
 sum(exp(-ln(2) * extract(epoch FROM (:as_of - first_original)) / 86400) + CASE WHEN first_original >= :as_of - interval '6 hours' THEN 0.5 ELSE 0 END) AS heat
 FROM groups WHERE first_original >= :hot_start AND first_original <= :as_of GROUP BY event_id
), candidates AS (
 SELECT e.id, e.first_seen_at, t.*, coalesce(h.active_publishers,0) AS active_publishers, h.heat,
 CASE WHEN early.reported_precision='time' THEN early.reported_at END AS earliest_reported_at, early.reported_date AS earliest_reported_date,
 coalesce(early.reported_precision,'unknown') AS earliest_reported_precision,
 CASE WHEN late.reported_precision='time' THEN late.reported_at END AS latest_reported_at, late.reported_date AS latest_reported_date,
 coalesce(late.reported_precision,'unknown') AS latest_reported_precision,
 CASE WHEN :sort='important' AND e.public_impact->>'status'='supported' AND e.public_impact->'is_urgent'='true'::jsonb
 AND t.earliest_lower >= :as_of - interval '48 hours'
 AND CASE WHEN e.public_impact->>'assessed_at' IS NULL THEN true WHEN pg_input_is_valid(e.public_impact->>'assessed_at', 'timestamptz') THEN (e.public_impact->>'assessed_at')::timestamptz <= :as_of ELSE false END
 AND jsonb_typeof(e.public_impact->'evidence')='array' AND jsonb_array_length(CASE WHEN jsonb_typeof(e.public_impact->'evidence')='array' THEN e.public_impact->'evidence' ELSE '[]'::jsonb END) > 0
 AND NOT EXISTS (SELECT 1 FROM jsonb_array_elements(CASE WHEN jsonb_typeof(e.public_impact->'evidence')='array' THEN e.public_impact->'evidence' ELSE '[]'::jsonb END) evidence
 WHERE NOT EXISTS (SELECT 1 FROM bounded a WHERE a.event_id=e.id AND a.content_basis='original' AND jsonb_typeof(evidence->'article_id')='number' AND jsonb_typeof(evidence->'quote')='string' AND a.id::text=evidence->>'article_id'
 AND length(trim(regexp_replace(normalize(evidence->>'quote', NFKC), '\s+', ' ', 'g'))) > 0
 AND strpos(trim(regexp_replace(normalize(coalesce(a.content,''), NFKC), '\s+', ' ', 'g')), trim(regexp_replace(normalize(evidence->>'quote', NFKC), '\s+', ' ', 'g'))) > 0))
 THEN 1 ELSE 0 END AS boosted,
 CASE WHEN t.earliest_lower IS NULL THEN 0 ELSE 1 END AS known,
 CASE WHEN t.earliest_lower IS NULL THEN extract(epoch FROM e.first_seen_at)
 WHEN :sort='newest' THEN extract(epoch FROM t.earliest_lower)
 WHEN :sort='hot' THEN h.heat ELSE coalesce(e.score_final,-1) END AS metric,
 extract(epoch FROM CASE WHEN :sort='hot' THEN t.latest_lower ELSE t.earliest_lower END) AS tie_time
 FROM events e LEFT JOIN times t ON t.event_id=e.id LEFT JOIN heat h ON h.event_id=e.id
 LEFT JOIN LATERAL (SELECT reported_at, reported_date, reported_precision FROM bounded WHERE event_id=e.id AND lower_bound IS NOT NULL ORDER BY lower_bound,id LIMIT 1) early ON true
 LEFT JOIN LATERAL (SELECT reported_at, reported_date, reported_precision FROM bounded WHERE event_id=e.id AND lower_bound IS NOT NULL ORDER BY lower_bound DESC,id DESC LIMIT 1) late ON true
 WHERE e.first_seen_at <= :as_of AND (
 (t.earliest_lower IS NULL AND :period='all') OR
 (t.earliest_lower IS NOT NULL AND ((:sort='hot' AND h.active_publishers > 0) OR (:sort!='hot' AND (CAST(:start AS timestamptz) IS NULL OR t.earliest_lower >= :start)))))
)
SELECT *, coalesce(tie_time,0) AS order_time FROM candidates
WHERE (:unread_only=false OR NOT EXISTS (SELECT 1 FROM event_read_states r WHERE r.event_id=candidates.id AND r.is_read))
AND (:has_cursor=false OR (boosted,known,metric,coalesce(tie_time,0),id) < (:k0,:k1,:k2,:k3,:k4))
ORDER BY boosted DESC, known DESC, metric DESC, coalesce(tie_time,0) DESC, id DESC LIMIT :limit
"""


def feed_page(
    session: Session,
    sort: str,
    period: str,
    limit: int,
    now: datetime,
    cursor: str | None,
    unread_only: bool = False,
) -> FeedPage:
    aliases, version = publisher_aliases()
    parsed = decode_cursor(cursor, sort, period, now, unread_only) if cursor else None
    as_of = parsed["as_of"] if parsed else now
    start = window_start(period, as_of)
    generation = session.scalar(
        text(
            """SELECT md5(coalesce(string_agg(id::text || coalesce(score_final::text,'') || coalesce(scored_at::text,'') || coalesce(public_impact::text,''), ',' ORDER BY id), '') || (SELECT coalesce(string_agg(id::text || ':' || event_id::text || coalesce(reported_at::text,'') || coalesce(reported_date::text,'') || reported_precision || coalesce(publisher_group,'') || md5(coalesce(content,'')) || content_basis, ',' ORDER BY id),'') FROM articles WHERE fetched_at <= :as_of)) FROM events WHERE first_seen_at <= :as_of"""
        ),
        {"as_of": as_of},
    )
    if parsed and parsed["generation"] != generation:
        raise HTTPException(409, "feed_changed_restart")
    key = parsed["key"] if parsed else [0, 0, 0, 0, 0]
    params = {
        "as_of": as_of,
        "unread_only": unread_only,
        "aliases": json.dumps(aliases),
        "sort": sort,
        "period": period,
        "start": start,
        "hot_start": start or as_of - timedelta(hours=24),
        "limit": limit + 1,
        "has_cursor": bool(parsed),
        **{f"k{i}": v for i, v in enumerate(key)},
    }
    rows = [dict(row) for row in session.execute(text(_SQL), params).mappings()]
    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        last = rows[-1]
        payload = {
            "v": version,
            "sort": sort,
            "range": period,
            "as_of": as_of.isoformat(),
            "generation": generation,
            "unread_only": unread_only,
            "key": [
                last["boosted"],
                last["known"],
                float(last["metric"]),
                float(last["order_time"]),
                last["id"],
            ],
        }
        next_cursor = (
            base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode())
            .decode()
            .rstrip("=")
        )
    return FeedPage(
        rows,
        as_of,
        next_cursor,
        start or (as_of - timedelta(hours=24) if sort == "hot" else None),
        version,
    )
