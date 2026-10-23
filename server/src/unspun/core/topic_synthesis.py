"""Pinned manual input, structural guards and live qualification of reviewed topic text."""

import json
from datetime import datetime
from typing import Any, Literal
from uuid import UUID, uuid5

from sqlalchemy import select
from sqlalchemy.orm import Session

from unspun.core.config import get_settings
from unspun.core.content import fingerprint
from unspun.core.sources import Source
from unspun.core.synthesis_contracts import (
    CHECKS,
    MANUAL_VERSION,
    ManualReview,
    SynthesisDraft,
    SynthesisReview,
    supported,
    synthesis_contract,
    targets,
    text_contract,
)
from unspun.core.synthesis_models import TopicSynthesis
from unspun.core.topic_contracts import EvidenceRef
from unspun.core.topic_models import Topic, TopicChange, TopicDerivation, TopicUpdate
from unspun.core.topics import topic_snapshot, validate_topic_evidence, validate_version


def synthesis_input(
    session: Session,
    topic_id: UUID,
    expected_revision: int,
    reviewer: ManualReview,
    *,
    sources: list[Source],
    now: datetime,
    response_mode: Literal["live", "mock"],
) -> dict[str, Any]:
    topic = session.get(Topic, str(topic_id), populate_existing=True)
    if topic is None or topic.revision != expected_revision:
        raise ValueError("topic revision changed")
    snapshot = topic_snapshot(session, topic, sources, now)
    if len(snapshot["members"]) > 8:
        raise ValueError("synthesis requires at most eight explicitly reviewed members")
    if response_mode == "live":
        for item in snapshot["updates"]:
            history = session.get(TopicChange, (str(topic_id), item["row"]["revision"]))
            if history is not None and history.actor == "r2-synthesis-worker:mock":
                raise ValueError(
                    "mock progress cannot seed live synthesis; use a fresh reviewed topic"
                )
    manual: list[dict[str, Any]] = []
    for member in snapshot["members"]:
        history = session.get(TopicChange, (str(topic_id), member["revision"]))
        if (
            member["decision_version"] != MANUAL_VERSION
            or history is None
            or history.command.get("action") != "member"
            or not history.actor.strip()
            or not history.reason.strip()
            or history.after != member
        ):
            raise ValueError("synthesis requires explicitly reviewed manual member versions")
        manual.append(
            {
                "article_id": member["article_id"],
                "material_id": member["material_id"],
                "revision": member["revision"],
                "actor": history.actor,
                "reason": history.reason,
                "evidence": member["evidence"],
                "source_url": member["input_snapshot"]["material"]["source_url"],
            }
        )
    packet = {
        "topic_id": str(topic_id),
        "expected_revision": expected_revision,
        "snapshot": snapshot,
        "manual_members": manual,
        "reviewer": reviewer.model_dump(mode="json"),
        "contract": synthesis_contract(),
        "response_mode": response_mode,
    }
    if len(json.dumps(packet, ensure_ascii=False).encode()) > 256 * 1024:
        raise ValueError("synthesis input exceeds bounded material packet; no truncation")
    return packet


def prompt_packet(packet: dict[str, Any], draft: dict[str, Any] | None = None) -> dict[str, Any]:
    snapshot = packet["snapshot"]
    value: dict[str, Any] = {
        "definition": snapshot["definition"],
        "members": [
            {
                "relation": m["relation"],
                "basis": m["basis"],
                "content": m["input_snapshot"]["content"],
                "source_url": m["input_snapshot"]["material"]["source_url"],
            }
            for m in snapshot["members"]
        ],
        "previous_progress": snapshot["updates"],
        "output_schema": SynthesisDraft.model_json_schema(),
    }
    if draft is not None:
        value.update(
            draft=draft,
            targets=targets(SynthesisDraft.model_validate(draft)),
            dimensions=list(CHECKS),
            output_schema=SynthesisReview.model_json_schema(),
        )
    return value


def validate_draft(session: Session, packet: dict[str, Any], draft: SynthesisDraft) -> None:
    """Only deterministic integrity checks. The independent audit still checks meaning."""
    members = {m["article_id"]: m for m in packet["snapshot"]["members"]}
    refs: list[EvidenceRef] = []
    for item in (*draft.contributions, *draft.overview, *draft.guide):
        for ref in item.evidence:
            member = members.get(ref.article_id)
            if member is None or member["material_id"] != ref.material_id:
                raise ValueError("citation is outside the fixed member material set")
            refs.append(ref)
    if sum(len(r.quote.encode()) for r in refs) > 16384:
        raise ValueError("total quoted evidence exceeds the registered bound")
    validate_topic_evidence(session, tuple(refs))
    if {r.article_id for c in draft.contributions for r in c.evidence} != set(members):
        raise ValueError("contribution classification must cover the fixed member set")
    previous = {u["row"]["update_id"]: u for u in packet["snapshot"]["updates"]}
    for item in draft.contributions:
        for time in (item.occurred, item.reported):
            if time.basis and not any(time.basis in ref.quote for ref in item.evidence):
                raise ValueError("each temporal basis must occur in its own cited evidence")
        if item.change == "none":
            continue
        if all(members[r.article_id]["relation"] == "reprint" for r in item.evidence):
            raise ValueError("reprints cannot establish substantive progress")
        if (
            item.classification == "discussion_focus"
            and packet["snapshot"]["definition"]["kind"] != "issue"
        ):
            raise ValueError("discussion focus requires an issue topic")
        assert item.progress_key
        key = str(uuid5(UUID(packet["topic_id"]), item.progress_key))
        old = previous.get(key)
        if item.change == "new" and old is not None:
            raise ValueError("existing progress key requires an explicit correction")
        if item.change == "correction":
            if old is None or not old["check"]["valid"]:
                raise ValueError("correction requires current, supported previous progress")
            payload = old["row"]["payload"]
            if any(item.model_dump(mode="json")[k] != payload[k] for k in ("occurred", "reported")):
                raise ValueError("text correction cannot refresh original progress times")
            if item.text == payload["summary"]:
                raise ValueError("duplicate assertion is not a progress correction")


def retained_response_valid(session: Session, row: TopicSynthesis, *, review: bool) -> bool:
    """Read-time and successor-time binding to the original settled response."""
    from unspun.core.billing_models import BilledRequest
    from unspun.core.llm import LlmError, parse_json_content
    from unspun.core.task_models import PipelineTask

    receipt = row.review_receipt if review else row.generation_receipt
    payload = row.review if review else row.draft
    if receipt is None or payload is None:
        return False
    call = session.get(BilledRequest, receipt["request_id"], populate_existing=True)
    if call is None or call.task_id is None or call.response_payload is None:
        return False
    task = session.get(PipelineTask, call.task_id, populate_existing=True)
    if (
        task is None
        or call.status != "responded"
        or call.usage_id is None
        or call.request_fingerprint != receipt["request_fingerprint"]
        or fingerprint(call.response_payload) != receipt["response_fingerprint"]
        or call.task_attempt_id != receipt["original_attempt_id"]
        or call.object_key != "topic:" + row.topic_id
        or task.input_fingerprint != receipt["input_fingerprint"]
        or fingerprint(task.payload) != task.input_fingerprint
        or ("mock" if call.response_payload.get("unspun_mock") is True else "live")
        != row.response_mode
        or (not review and (call.task_id != row.task_id or task.payload != row.input_snapshot))
        or (
            review
            and (
                task.payload.get("generation_key") != row.input_fingerprint
                or task.payload.get("draft_fingerprint") != fingerprint(row.draft)
            )
        )
    ):
        return False
    try:
        raw = parse_json_content(call.response_payload["choices"][0]["message"]["content"])
        parsed = (
            SynthesisReview.model_validate(raw) if review else SynthesisDraft.model_validate(raw)
        )
        return parsed.model_dump(mode="json") == payload
    except (LlmError, ValueError, KeyError, IndexError, TypeError):
        return False


def qualified_topic_text(
    session: Session,
    topic_id: UUID,
    *,
    sources: list[Source],
    now: datetime,
) -> dict[str, Any] | None:
    """Future backend reader boundary; no endpoint, ranking or production activation here."""
    if not get_settings().r2_topic_publication_enabled:
        return None
    row = session.scalar(
        select(TopicSynthesis)
        .where(TopicSynthesis.topic_id == str(topic_id))
        .order_by(TopicSynthesis.created_at.desc(), TopicSynthesis.task_id.desc())
        .limit(1)
        .execution_options(populate_existing=True)
    )
    if (
        row is None
        or row.status != "applied"
        or row.response_mode != "live"
        or row.applied is None
        or row.review is None
        or row.review_receipt is None
        or row.input_snapshot["contract"] != synthesis_contract()
    ):
        return None
    draft = SynthesisDraft.model_validate(row.draft)
    if not supported(draft, SynthesisReview.model_validate(row.review)):
        return None
    if not retained_response_valid(session, row, review=False) or not retained_response_valid(
        session, row, review=True
    ):
        return None
    for kind, revision in row.applied["derivations"].items():
        derived = session.get(
            TopicDerivation, (str(topic_id), kind, revision), populate_existing=True
        )
        if (
            derived is None
            or not validate_version(
                session, derived, sources=sources, now=now, contract=text_contract()
            ).valid
        ):
            return None
    progress: list[dict[str, Any]] = []
    for item in row.applied["updates"]:
        update = session.get(
            TopicUpdate,
            (str(topic_id), item["update_id"], item["revision"]),
            populate_existing=True,
        )
        if update is None or not validate_version(session, update, sources=sources, now=now).valid:
            return None
        progress.append(
            draft.contributions[int(item["contribution_index"])].model_dump(mode="json")
        )
    return {
        "topic_id": str(topic_id),
        "version": row.input_fingerprint,
        "overview": [c.model_dump(mode="json") for c in draft.overview],
        "guide": [c.model_dump(mode="json") for c in draft.guide],
        "progress": progress,
        "material_scope": [
            m["input_snapshot"]["content"] for m in row.input_snapshot["snapshot"]["members"]
        ],
        "manual_review": row.input_snapshot["reviewer"],
    }
