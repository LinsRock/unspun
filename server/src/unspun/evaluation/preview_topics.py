"""Explicit R2-10 engineering preview over retained real material.

Run only as a separate ASGI factory, never imported by the production app.
No provider client, synthesis task, synthetic approval or budget allocation.
The retained mock prose stays labelled and the production qualifier rejects it.
"""

import argparse
import gzip
import hashlib
import ipaddress
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import JSONResponse, Response

from unspun.api.admin.auth import require_admin_identity
from unspun.api.contents import ReadDb
from unspun.api.contents import details as content_detail
from unspun.api.contents import feed as content_feed
from unspun.api.feed_preferences import Db, require_write
from unspun.api.reader import TargetFeedbackDelete, TargetFeedbackInput, TopicFollowInput
from unspun.core.config import get_settings
from unspun.core.content import fingerprint
from unspun.core.content_feed import item_out, rules, term_matches
from unspun.core.content_publication import qualified_item
from unspun.core.db import get_engine
from unspun.core.hybrid_contracts import HybridRules
from unspun.core.hybrid_feed import page
from unspun.core.hybrid_ranking import Candidate, time_key, topic_preference_score
from unspun.core.models import Article
from unspun.core.reader import Mutation, mutate
from unspun.core.reader_models import ReaderInterest, TopicPreference
from unspun.core.sources import Source, load_sources
from unspun.core.synthesis_contracts import MANUAL_VERSION
from unspun.core.topic_contracts import DefineTopic, EvidenceRef, SetMember, TopicMutation
from unspun.core.topic_models import Topic
from unspun.core.topics import mutate_topic, topic_snapshot
from unspun.evaluation.hybrid_feed import ARTIFACT, SHA256
from unspun.evaluation.member_quality import seed_packages

ROOT = Path(__file__).resolve().parents[4]
REPLAY = ROOT / "docs/acceptance/r2-07/manual-replay.json"


def require_environment() -> None:
    settings = get_settings()
    url = make_url(settings.database_url)
    if not (
        settings.admin_local_preview
        and url.host in {"localhost", "127.0.0.1", "::1"}
        and (url.database or "").startswith("unspun_r210_preview_")
        and not any(
            (
                settings.r1_worker_enabled,
                settings.r2_member_processing_enabled,
                settings.r2_synthesis_enabled,
                settings.r2_topic_publication_enabled,
                settings.r1_local_preview,
                settings.openrouter_api_key,
            )
        )
        and settings.r2_hybrid_enabled
        and settings.r2_topic_preferences_enabled
    ):
        raise RuntimeError(
            "R2-10 preview requires an isolated loopback database and no paid runtime"
        )


def groups() -> list[dict[str, Any]]:
    return json.loads(REPLAY.read_text())["sets"]


def seed() -> None:
    require_environment()
    artifact = ROOT / ARTIFACT
    if hashlib.sha256(artifact.read_bytes()).hexdigest() != SHA256:
        raise ValueError("retained input checksum changed")
    sources = load_sources()
    with Session(get_engine()) as session, session.begin():
        if session.scalar(select(Article.id).limit(1)) or session.scalar(select(Topic.id).limit(1)):
            raise ValueError("seed requires an empty new preview database; never overwrite")
        seed_packages(
            session,
            json.loads(gzip.decompress(artifact.read_bytes()))["packages"],
            material_offset=0,
        )
        for group in groups():
            topic_id = UUID(group["topic_id"])
            changes: list[Any] = [
                DefineTopic(
                    kind="issue",
                    title=group["title"],
                    domains=("technology",) if group["status"] == "applied" else ("culture",),
                )
            ]
            for member in group["manual_members"]:
                changes.append(
                    SetMember(
                        article_id=member["article_id"],
                        material_id=member["material_id"],
                        relation=member["relation"],
                        basis="Retained engineering preview membership",
                        decision_version=MANUAL_VERSION,
                        evidence=(EvidenceRef.model_validate(member["evidence"]),),
                    )
                )
            for revision, change in enumerate(changes):
                mutate_topic(
                    session,
                    topic_id,
                    TopicMutation(
                        mutation_id=uuid4(),
                        expected_revision=revision,
                        actor="codex:r2-10-engineering-preview",
                        reason="Retained manually selected material; no real model quality claim",
                        change=change,
                    ),
                    sources=sources,
                    now=datetime.now(UTC),
                )
    print("Seeded 12 retained real contents and 2 labelled engineering topics; paid tasks: 0")


def preview_detail(session: Session, identity: UUID) -> dict[str, Any] | None:
    require_environment()
    group = next((g for g in groups() if g["topic_id"] == str(identity)), None)
    topic = session.get(Topic, str(identity), populate_existing=True)
    if group is None or topic is None or topic.revision != 1 + len(group["manual_members"]):
        return None
    sources, now = load_sources(), datetime.now(UTC)
    try:
        snapshot = topic_snapshot(session, topic, sources, now)
    except ValueError:
        return None
    related: list[dict[str, Any]] = []
    for member in snapshot["members"]:
        item = qualified_item(
            session, member["article_id"], preview=False, as_of=now, sources=sources
        )
        if item is None:
            return None
        related.append({**item_out(item, {}, sources), "relation": member["relation"]})
    draft = group["draft"]
    return {
        "id": topic.id,
        "title": topic.title,
        "kind": topic.kind,
        "domains": topic.domains,
        "version": fingerprint([snapshot, draft]),
        "revision": topic.revision,
        "overview": draft["overview"],
        "guide": draft["guide"],
        "progress": [c for c in draft["contributions"] if c["change"] != "none"],
        "context": [
            c for c in draft["contributions"] if c["classification"] in {"background", "opinion"}
        ],
        "related": related,
        "engineering_preview": True,
    }


def preview_eligible(session: Session, identity: UUID) -> bool:
    return preview_detail(session, identity) is not None


def preview_candidates(
    session: Session,
    sources: list[Source],
    policy: HybridRules,
    interests: list[ReaderInterest],
    now: datetime,
) -> tuple[list[Candidate], dict[str, int]]:
    require_environment()
    result: list[Candidate] = []
    reader = rules()
    for group in groups():
        detail = preview_detail(session, UUID(group["topic_id"]))
        if detail is None:
            continue
        matched = [
            i
            for i in interests
            if (
                i.kind == "domain"
                and i.target["value"] in detail["domains"]
                or i.kind == "term"
                and term_matches(i.target["value"], detail["title"])
            )
        ]
        score = min(
            reader.interest_cap, sum(reader.interest_weights.get(i.kind, 0) for i in matched)
        )
        preference = session.get(TopicPreference, detail["id"])
        direct = topic_preference_score(
            preference.followed if preference else False,
            preference.feedback if preference else None,
            policy,
            reader,
        )
        stamps = [
            {**c[kind], "kind": kind}
            for c in detail["progress"]
            for kind in ["occurred" if c["occurred"]["precision"] != "unknown" else "reported"]
        ]
        result.append(
            Candidate(
                "topic",
                detail["id"],
                detail["version"],
                detail["title"],
                tuple(sorted({c["source_id"] for c in detail["related"]})),
                tuple(detail["domains"]),
                max(stamps, key=time_key)
                if stamps
                else {"kind": "occurred", "precision": "unknown"},
                {
                    **detail,
                    "material_scope": [
                        {"source_id": c["source_id"], "scope": c["material_scope"]}
                        for c in detail["related"]
                    ],
                },
                {
                    "score": score + direct["topic_preference_score"],
                    "interest": score,
                    "matched_interests": [i.resource_key for i in matched],
                    **direct,
                },
                lanes=("readable",),
            )
        )
    return result, {"engineering_preview": len(result)}


def create_app() -> FastAPI:
    require_environment()
    from unspun.api.app import app as production_app

    app = FastAPI(
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        dependencies=[Depends(require_admin_identity)],
    )

    def preview_write(request: Request) -> None:
        # A LAN phone may reach the loopback API through the local Vite proxy.
        # This exception exists only in the guarded, keyless evaluation app.
        require_environment()
        origin = urlsplit(request.headers.get("origin", ""))
        try:
            local = (
                origin.hostname == "localhost"
                or ipaddress.ip_address(origin.hostname or "").is_private
            )
        except ValueError:
            local = False
        if (
            not local
            or origin.scheme not in {"http", "https"}
            or origin.netloc != request.headers.get("host")
            or origin.path
            or origin.query
            or request.headers.get("sec-fetch-site") not in {None, "same-origin", "none"}
        ):
            raise HTTPException(403, "Same-origin local preview required")

    app.dependency_overrides[require_write] = preview_write

    @app.middleware("http")
    async def isolated(request: Request, call_next: RequestResponseEndpoint) -> Response:
        require_environment()
        allowed_writes = {
            "/api/topic-follows",
            "/api/target-feedback",
            "/api/interests",
            "/api/feedback",
            "/api/reader-preferences",
            "/api/feed-preferences",
        }
        if not request.client or request.client.host not in {"127.0.0.1", "::1"}:
            return JSONResponse({"detail": "Loopback preview only"}, status_code=403)
        if request.url.path.startswith("/api/admin") or (
            request.method not in {"GET", "HEAD"} and request.url.path not in allowed_writes
        ):
            return JSONResponse(
                {"detail": "No processing or administration in preview"}, status_code=403
            )
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Unspun-Engineering-Preview"] = "r2-10"
        return response

    @app.get("/api/reading-capabilities")
    def capabilities() -> dict[str, Any]:
        return {
            "hybrid": True,
            "topic_preferences": True,
            "home": "discover",
            "engineering_preview": True,
        }

    @app.get("/api/feed")
    def feed(
        request: Request,
        session: ReadDb,
        mode: Literal["content", "mixed"] = "content",
        sort: Literal["recommended", "latest"] = "recommended",
        cursor: str | None = Query(default=None, max_length=2000),
        limit: int = Query(default=20, ge=1, le=50),
    ) -> dict[str, Any]:
        if mode == "content":
            return content_feed(request, session, mode, sort, cursor, limit)
        return {
            **page(
                session,
                sort=sort,
                cursor=cursor,
                limit=limit,
                now=datetime.now(UTC),
                topic_loader=preview_candidates,
            ),
            "engineering_preview": True,
        }

    @app.get("/api/topics/{identity}")
    def topic(identity: UUID, session: ReadDb) -> dict[str, Any]:
        result = preview_detail(session, identity)
        if result is None:
            raise HTTPException(404, "Engineering topic is unavailable")
        return result

    @app.get("/api/contents/{identity}")
    def content(identity: int, request: Request, session: ReadDb) -> dict[str, Any]:
        result = content_detail(identity, request, session)
        result["guide"] = {
            "status": "unavailable",
            "reason": "preview_no_paid",
            "payload": None,
            "task_id": None,
            "requestable": False,
        }
        return result

    def change(
        session: Session,
        body: Mutation,
        target: dict[str, Any],
        kind: str,
        value: dict[str, Any] | None,
    ) -> dict[str, Any]:
        return mutate(
            session, body, kind, target, value, include_topics=True, topic_eligible=preview_eligible
        )

    @app.put("/api/topic-follows", dependencies=[Depends(require_write)])
    def follow(body: TopicFollowInput, session: Db) -> dict[str, Any]:
        return change(
            session, body, body.target.model_dump(mode="json"), "topic_follow", {"active": True}
        )

    @app.delete("/api/topic-follows", dependencies=[Depends(require_write)])
    def unfollow(body: TopicFollowInput, session: Db) -> dict[str, Any]:
        return change(session, body, body.target.model_dump(mode="json"), "topic_follow", None)

    def feedback(
        body: TargetFeedbackDelete, session: Session, value: dict[str, Any] | None
    ) -> dict[str, Any]:
        target = (
            {"content_id": body.target.id}
            if body.target.type == "content"
            else body.target.model_dump(mode="json")
        )
        return change(
            session,
            body,
            target,
            "feedback" if body.target.type == "content" else "topic_feedback",
            value,
        )

    @app.put("/api/target-feedback", dependencies=[Depends(require_write)])
    def put_feedback(body: TargetFeedbackInput, session: Db) -> dict[str, Any]:
        return feedback(body, session, {"value": body.value})

    @app.delete("/api/target-feedback", dependencies=[Depends(require_write)])
    def delete_feedback(body: TargetFeedbackDelete, session: Db) -> dict[str, Any]:
        return feedback(body, session, None)

    app.include_router(production_app.router)
    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", required=True, action="store_true")
    parser.parse_args()
    seed()
