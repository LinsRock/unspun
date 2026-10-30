"""Budgeted R1 card/guide comparison on explicitly supplied hash-pinned materials."""

import argparse
import hashlib
import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from unspun.core.billing import (
    EVALUATION_LIMIT,
    CallContext,
    DatabaseJournal,
    budget_status,
    initialize_budget,
)
from unspun.core.billing_models import BilledRequest
from unspun.core.content import (
    Author,
    ContentMetadata,
    ContentTime,
    MaterialScope,
    Paragraph,
    fingerprint,
)
from unspun.core.content_reading import ContentInput
from unspun.core.db import get_engine
from unspun.core.llm import LlmClient
from unspun.core.models import Article
from unspun.evaluation.legacy.summarize import summarize_article
from unspun.evaluation.run_quality import (
    BudgetLedger,
    EvaluationJournal,
    load_key_from_ssh,
    require_isolated_database,
)
from unspun.pipeline.content_processing import organize, processing_fingerprint


def material_input(item: dict[str, Any], index: int) -> ContentInput:
    text = str(item["text"])
    if text and hashlib.sha256(text.encode()).hexdigest() != item["material_sha256"]:
        raise ValueError("material fingerprint differs from the frozen input")
    if item.get("metadata"):
        metadata = ContentMetadata.model_validate(item["metadata"])
    else:
        publication = item["publication"]
        raw = publication.get("value")
        kind = publication.get("kind", "original")
        if item["id"] in {"C24", "C25", "C26"}:
            kind = "editorial"
        if item["id"] in {"C20", "C21", "C41", "C42"}:
            kind = "reprint"
        if item["scope"] == "question_background":
            kind = "question_created"
        times = ()
        if raw:
            times = (
                ContentTime.model_validate(
                    {
                        "kind": kind,
                        "precision": "time" if "T" in raw else "date",
                        "at": datetime.fromisoformat(raw) if "T" in raw else None,
                        "on": date.fromisoformat(raw) if "T" not in raw else None,
                        "basis": publication.get("basis", "frozen-source-evidence"),
                    }
                ),
            )
        metadata = ContentMetadata(
            form="audio"
            if item["id"] == "C09"
            else "video"
            if item["scope"] == "media_description"
            else "question"
            if item["scope"] == "question_background"
            else "article",
            genre="old_report" if item["id"] in {"C11", "C19"} else item["genre"],
            platform=item["publisher"],
            publisher=item["publisher"],
            authors=(Author(name=item["author"], role="unknown", basis="frozen-source-byline"),)
            if item["author"]
            else (),
            times=times,
        )
    return ContentInput(
        article_id=index + 1,
        material_id=index + 1,
        source_id="eval:" + item["id"],
        title=item["title"],
        metadata=metadata,
        scope=cast(MaterialScope, item["scope"]),
        paragraphs=(Paragraph(text=text),) if text else (),
        material_fingerprint=item["material_sha256"] or "none",
        metadata_fingerprint=fingerprint(metadata.model_dump(mode="json")),
        extractor_version="frozen-r0-observed-material-v1",
        material_observed_at=datetime.fromisoformat(item["observed_at"]),
        canonical_content_id=21 if item["id"] == "C41" else None,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--materials", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--kind", choices=["card", "guide", "legacy"], default="card")
    parser.add_argument("--cards", type=Path, action="append", default=[])
    parser.add_argument("--case", action="append", default=[])
    parser.add_argument("--key-source-ssh")
    args = parser.parse_args()
    if args.output.exists() or args.output.with_suffix(".accounting.json").exists():
        raise ValueError("preserve existing evaluation evidence; choose a new output")
    if args.output.resolve().is_relative_to(Path(__file__).resolve().parents[4]):
        raise ValueError("full model outputs must stay outside the repository")
    require_isolated_database()
    if args.key_source_ssh:
        load_key_from_ssh(args.key_source_ssh)
    items = json.loads(args.materials.read_text())["inputs"]
    selected = [
        (i, item)
        for i, item in enumerate(items)
        if item.get("live_generation_sample", True) and (not args.case or item["id"] in args.case)
    ]
    if args.case and {item["id"] for _, item in selected} != set(args.case):
        raise ValueError("unknown evaluation case")
    contents = [(item, material_input(item, index)) for index, item in selected]
    cards: dict[str, dict[str, Any]] = {}
    for path in args.cards:
        for line in path.read_text().splitlines():
            row = json.loads(line)
            if row.get("status") == "ready":
                cards[row["id"]] = row
    with Session(get_engine()) as session:
        initialize_budget(session, scope="evaluation")
        session.commit()
        previous = set(session.scalars(select(BilledRequest.id)))
    ledger = BudgetLedger(float(EVALUATION_LIMIT), 150)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as output:
        for item, content in contents:
            kind: Literal["card", "guide"] = "guide" if args.kind == "guide" else "card"
            key = "r1-candidate:" + item["id"] + ":" + processing_fingerprint(content, kind)
            record = {
                "id": item["id"],
                "kind": args.kind,
                "material_sha256": item["material_sha256"],
                "input_fingerprint": processing_fingerprint(content, kind),
                "at": datetime.now(UTC).isoformat(),
            }
            with (
                LlmClient(
                    context=CallContext(stage=kind, phase="generate", logical_key=key),
                    journal_factory=lambda s: EvaluationJournal(
                        DatabaseJournal(s.get_bind().engine), ledger
                    ),
                ) as gen,
                LlmClient(
                    context=CallContext(stage=kind, phase="review", logical_key=key),
                    journal_factory=lambda s: EvaluationJournal(
                        DatabaseJournal(s.get_bind().engine), ledger
                    ),
                ) as reviewer,
            ):
                try:
                    with Session(get_engine()) as session:
                        if args.kind == "legacy":
                            article = Article(
                                id=content.article_id,
                                title=content.title,
                                content=content.text(),
                                source_id=content.source_id,
                                url=item["url"],
                                lang="zh",
                                processing_track="legacy",
                            )
                            summarize_article(session, gen, article)
                            record.update(
                                status="captured",
                                title_zh=article.title_zh,
                                summary_zh=article.summary_zh,
                                grounding=article.summary_grounding,
                            )
                        else:
                            ready_card = cards.get(item["id"])
                            if (
                                kind == "guide"
                                and ready_card
                                and ready_card["input_fingerprint"]
                                != processing_fingerprint(content, "card")
                            ):
                                raise ValueError("guide card input/version differs")
                            result = organize(
                                session,
                                gen,
                                reviewer,
                                content,
                                kind=kind,
                                card=ready_card["payload"] if ready_card else None,
                            )
                            record.update(
                                status=result.status,
                                reason=result.reason,
                                payload=result.payload,
                                review=result.review,
                            )
                except Exception as error:
                    record.update(status="error", error_kind=type(error).__name__)
                identities = gen.call_ids + reviewer.call_ids
                record.update(
                    physical_call_ids=identities,
                    new_request_ids=[i for i in identities if i not in previous],
                )
            output.write(json.dumps(record, ensure_ascii=False) + "\n")
            output.flush()
            print(
                json.dumps(
                    {
                        "id": item["id"],
                        "status": record["status"],
                        "known_run_cost_usd": ledger.cost_usd,
                    }
                ),
                flush=True,
            )
    with Session(get_engine()) as session:
        accounting = budget_status(session)
    with args.output.with_suffix(".accounting.json").open("x") as output:
        json.dump(
            {
                "known_run_cost_usd": ledger.cost_usd,
                "new_physical_calls": ledger.calls,
                "accounting": accounting,
                "materials_file_sha256": hashlib.sha256(args.materials.read_bytes()).hexdigest(),
            },
            output,
            indent=2,
            default=str,
        )


if __name__ == "__main__":
    main()
