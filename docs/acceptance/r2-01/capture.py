"""One-off R2-01 evidence capture: SELECT-only DB snapshot and optional free GET /key."""

import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx
import unspun
from sqlalchemy import text
from sqlalchemy.orm import Session
from unspun.core.billing import budget_status
from unspun.core.billing_admin import provider_key_status
from unspun.core.config import get_settings
from unspun.core.content_feed import page, rank, reviewed, rules
from unspun.core.content_reading import CARD_VERSION, GUIDE_VERSION, REVIEW_VERSION
from unspun.core.db import get_engine
from unspun.core.sources import load_sources
from unspun.pipeline.content_processing import load_content, processing_fingerprint

mode = sys.argv[1]
settings = get_settings()
out = {
    "schema_version": "r2-01-readonly-snapshot-v1",
    "mode": mode,
    "capture_started_at": datetime.now(UTC).isoformat(),
    "python": {"executable": sys.executable, "unspun": unspun.__file__},
    "paid_calls_started_by_capture": 0,
}
engine = get_engine()
with engine.connect().execution_options(isolation_level="REPEATABLE READ") as conn:
    tx = conn.begin()
    conn.execute(text("SET TRANSACTION READ ONLY"))
    conn.execute(text("SET LOCAL statement_timeout = '30s'"))
    session = Session(bind=conn)

    def query(sql):
        return [dict(r) for r in conn.execute(text(sql)).mappings()]

    out["transaction"] = query(
        "SELECT transaction_timestamp() AS at, current_database() AS database, current_setting('transaction_read_only') AS read_only, current_setting('transaction_isolation') AS isolation"
    )[0]
    out["schema"] = query("SELECT version_num FROM alembic_version")
    out["budget"] = budget_status(session)
    out["policy"] = query(
        "SELECT id, scope, enabled, monthly_limit_usd, stage_caps, version, coverage_started_at, incident, provider_limit_usd, provider_usage_usd, provider_limit_kind, provider_observed_at FROM budget_policy"
    )
    out["carry"] = query("SELECT * FROM budget_carry ORDER BY month")
    out["known_ledger"] = query(
        "SELECT date_trunc('month', created_at) AS month, count(*) AS calls, sum(cost_usd::numeric) AS known_usd FROM llm_usage GROUP BY 1 ORDER BY 1"
    )
    out["requests"] = query(
        "SELECT b.id, b.stage, b.phase, b.purpose, b.model, b.status, b.reserved_usd, b.task_id, b.task_attempt_id, b.article_id, b.source_id, b.usage_id, b.provider_generation_id, b.http_status, b.started_at, b.ended_at, u.cost_usd::numeric AS known_usd FROM billed_requests b LEFT JOIN llm_usage u ON u.id = b.usage_id ORDER BY b.started_at, b.id"
    )
    if mode == "production":
        sources = load_sources()
        out["app_version"] = settings.app_version
        out["r1_worker_enabled"] = settings.r1_worker_enabled
        out["source_sha256"] = {
            str(p.relative_to(Path(unspun.__file__).parent)): hashlib.sha256(
                p.read_bytes()
            ).hexdigest()
            for p in sorted(Path(unspun.__file__).parent.rglob("*.py"))
        }
        out["authentication"] = {
            "admin_local_preview": settings.admin_local_preview,
            "r1_local_preview": settings.r1_local_preview,
            "access_configured": bool(
                settings.access_audience and settings.access_team_domain
            ),
        }
        out["models"] = {
            key: getattr(settings, key)
            for key in (
                "summary_model",
                "importance_model",
                "viewpoint_model",
                "digest_model",
                "embedding_model",
                "grounding_budget_24h_usd",
            )
        }
        out["contracts"] = {
            "card": CARD_VERSION,
            "guide": GUIDE_VERSION,
            "review": REVIEW_VERSION,
            "reader": rules().model_dump(),
        }
        out["config_sha256"] = {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(Path(settings.config_dir).glob("*.yml"))
        }
        out["sources"] = [s.model_dump(mode="json") for s in sources if s.r1]
        out["source_states"] = query("SELECT * FROM source_states ORDER BY source_id")
        out["article_counts"] = query(
            "SELECT processing_track, count(*) AS rows, count(*) FILTER (WHERE canonical_content_id IS NULL) AS canonical_rows FROM articles GROUP BY processing_track ORDER BY processing_track"
        )
        out["articles"] = query(
            "SELECT id, source_id, url, title, content_form, genre, r1_metadata, metadata_fingerprint, canonical_content_id, current_material_id, published_at, reported_at, reported_date, reported_precision, reported_basis, fetched_at FROM articles WHERE processing_track='r1' ORDER BY id"
        )
        out["materials"] = query(
            "SELECT m.id, m.article_id, m.input_fingerprint, m.text_fingerprint, m.metadata_fingerprint, m.extractor_version, m.schema_version, m.scope, m.access_status, m.completeness, m.completeness_basis, m.source_url, m.retrieved_at, m.response_status, m.response_fingerprint, jsonb_array_length(m.paragraphs) AS paragraph_count, (SELECT coalesce(sum(length(p->>'text')),0) FROM jsonb_array_elements(m.paragraphs) p) AS text_chars FROM content_materials m JOIN articles a ON a.id=m.article_id WHERE a.processing_track='r1' ORDER BY m.id"
        )
        out["derivations"] = query(
            "SELECT d.* FROM content_derivations d JOIN articles a ON a.id=d.article_id WHERE a.processing_track='r1' ORDER BY d.id"
        )
        out["observations"] = query(
            "SELECT o.id, o.article_id, o.source_id, o.item_key, o.observed_at, o.observation_fingerprint, o.rank, o.signals FROM content_observations o JOIN articles a ON a.id=o.article_id WHERE a.processing_track='r1' ORDER BY o.id"
        )
        out["tasks"] = query(
            "SELECT id, queue, kind, object_key, article_id, source_id, input_fingerprint, strategy_version, cycle_key, status, due_at, attempts, failures, max_attempts, claim_version, result, last_error, created_at, finished_at FROM pipeline_tasks ORDER BY id"
        )
        out["attempts"] = query(
            "SELECT id, task_id, claim_version, started_at, ended_at, status, error FROM task_attempts ORDER BY id"
        )
        out["reader_state"] = query("SELECT * FROM reader_state")
        now = conn.execute(text("SELECT transaction_timestamp()")).scalar_one()
        items = reviewed(
            session, preview=False, as_of=now, sources=sources, policy=rules()
        )
        out["publication"] = {
            "as_of": now,
            "published_ids": [i.article.id for i in items],
            "actual_browser_impressions": None,
            "impressions_missing_reason": "No impression telemetry; function replay is not browser display evidence.",
        }
        for sort in ("recommended", "latest"):
            ordered, snapshot = rank(session, items, now, sort, rules())
            out["publication"][sort] = {
                "ordered_ids": [i.article.id for i, _ in ordered],
                "ranking_snapshot": snapshot,
                "scores": [
                    {"article_id": i.article.id, **parts} for i, parts in ordered
                ],
                "first_page": page(
                    session, preview=False, sort=sort, cursor=None, limit=20, now=now
                ),
            }
        if len(sys.argv) > 2:
            ids = [int(v) for v in sys.argv[2].split(",")]
            out["selected_inputs"] = []
            for identity in ids:
                content = load_content(session, identity)
                material = query(
                    f"SELECT * FROM content_materials WHERE id={content.material_id}"
                )[0]
                out["selected_inputs"].append(
                    {
                        "input": content.model_dump(mode="json"),
                        "card_processing_fingerprint": processing_fingerprint(
                            content, "card"
                        ),
                        "material": material,
                    }
                )
    session.close()
    tx.rollback()
if mode == "production":
    with httpx.Client(
        base_url=settings.openrouter_base_url,
        headers={"Authorization": "Bearer " + settings.openrouter_api_key},
        timeout=30,
    ) as client:
        data = provider_key_status(client)
        out["provider"] = {
            key: data.get(key)
            for key in (
                "limit",
                "limit_remaining",
                "limit_reset",
                "usage",
                "usage_monthly",
                "is_management_key",
            )
        }
        out["provider"]["checked_at"] = datetime.now(UTC).isoformat()
        out["provider"]["method"] = "GET /api/v1/key"
out["capture_finished_at"] = datetime.now(UTC).isoformat()
print(json.dumps(out, default=str, ensure_ascii=False, indent=2))
