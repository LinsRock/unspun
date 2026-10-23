"""Offline R2-08 comparison over frozen exposed inputs and labelled layout fixtures.

Requires an empty migrated loopback unspun_r208_* database. All seed/preference
writes roll back. No LLM, provider query, allocation or production connection.
"""

import argparse
import gzip
import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from unspun.core.config import get_settings
from unspun.core.content import fingerprint
from unspun.core.content_feed import rules
from unspun.core.hybrid_contracts import HybridRules
from unspun.core.hybrid_ranking import Candidate, ordered, render_page
from unspun.core.hybrid_recall import content_candidates
from unspun.core.models import Article
from unspun.core.reader import InterestTarget, Mutation, mutate
from unspun.core.reader_models import ReaderInterest
from unspun.core.sources import load_sources
from unspun.evaluation.member_quality import seed_packages

ROOT = Path(__file__).resolve().parents[4]
ARTIFACT = "docs/evaluations/r2/member-grounding-exposed-inputs-v1.json.gz"
SHA256 = "817d1f85d9c9f10032aafe3675677af96014395197a083af16ae423cfe8cf322"
AS_OF = datetime(2026, 10, 23, 8, tzinfo=UTC)


def compare(candidates: list[Candidate]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for sort in ("recommended", "latest"):
        rows = ordered(candidates, sort, HybridRules(), rules())
        page = render_page(rows)
        unique = {c.id for c in candidates if c.protect}
        result[sort] = {
            "order": [f"{i['type']}:{i['id']}" for i in page],
            "rows": [
                {k: i[k] for k in ("type", "id", "version", "time", "presentation", "ranking")}
                for i in page
            ],
            "reference_cards": [i["id"] for i in page if i["presentation"] == "reference"],
            "unique_content_denominator": len(unique),
            "unique_content_compressed": sum(
                i["id"] in unique and i["presentation"] == "reference" for i in page
            ),
        }
    return result


def evaluate(session: Session) -> dict[str, Any]:
    artifact = ROOT / ARTIFACT
    assert hashlib.sha256(artifact.read_bytes()).hexdigest() == SHA256
    assert session.scalar(select(Article.id).limit(1)) is None, (
        "requires an empty isolated database"
    )
    raw: dict[str, Any] = json.loads(gzip.decompress(artifact.read_bytes()))
    seed_packages(session, raw["packages"], material_offset=0)
    sources, policy = load_sources(), HybridRules()
    plain, counts, _ = content_candidates(session, sources, policy, [], AS_OF, AS_OF)
    mutate(
        session,
        Mutation(version=0, mutation_id=uuid4()),
        "interest",
        InterestTarget(kind="domain", value="culture").model_dump(),
        {"active": True},
    )
    interests = list(session.scalars(select(ReaderInterest)))
    interested, _, _ = content_candidates(session, sources, policy, interests, AS_OF, AS_OF)
    replay_path = ROOT / "docs/acceptance/r2-07/manual-replay.json"
    replay: dict[str, Any] = json.loads(replay_path.read_text())
    group = next(g for g in replay["sets"] if g["status"] == "applied")
    mock = Candidate(
        "topic",
        group["topic_id"],
        fingerprint(group),
        group["title"],
        ("zaobao-world",),
        ("technology",),
        {"kind": "occurred", "precision": "unknown"},
        {"engineering_fixture": True, "overview": group["draft"]["overview"]},
        {"score": 0, "fixture": "R2-07 retained mock; ineligible for production"},
        lanes=("readable",),
    )
    # A synthetic duplicate is explicitly separate from the two real reports.
    original = next(c for c in interested if c.id == "9013")
    duplicate = replace(
        original,
        id="engineering-copy-9013",
        protect=False,
        version=fingerprint("engineering-copy-9013"),
    )
    mock_with_copy = replace(mock, duplicate_ids=(duplicate.id,))
    engineered = compare(interested + [duplicate, mock_with_copy])
    for mode in engineered.values():
        mode["duplicate_summary_pairs_before"] = 1
        mode["duplicate_summary_pairs_after"] = 1 - len(mode["reference_cards"])
    return {
        "contract": "r2-hybrid-v1",
        "as_of": AS_OF.isoformat(),
        "material_file": ARTIFACT,
        "sha256": SHA256,
        "reviewer": "Codex / agent_manual engineering audit; no human quality rating",
        "sample_ids": [p["original_id"] for p in raw["packages"]],
        "qualified_ids": [c.id for c in plain],
        "selected_by_lane": counts,
        "missing_important": len(plain),
        "missing_public_attention": len(plain),
        "real_material_no_preferences": compare(plain),
        "real_material_engineering_culture_interest": compare(interested),
        "offline_ineligible_mock_topic": compare(interested + [mock]),
        "engineering_duplicate_control": engineered,
        "real_duplicate_ground_truth": None,
        "real_topic_generation_quality": "unmeasured",
        "user_acceptance": None,
        "generation": 0,
        "embedding": 0,
        "paid_retries": 0,
        "provider_queries": 0,
        "production_writes": 0,
        "isolated_writes_rolled_back": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    url = make_url(get_settings().database_url)
    if url.host not in {"localhost", "127.0.0.1", "::1"} or not (url.database or "").startswith(
        "unspun_r208_"
    ):
        parser.error("only an explicit loopback unspun_r208_* database is allowed")
    if args.output.exists():
        parser.error("output exists; retain the previous result")
    engine = create_engine(url)
    with Session(engine) as session:
        result = evaluate(session)
        session.rollback()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {
                "qualified": len(result["qualified_ids"]),
                "paid_requests": 0,
                "real_quality": "unmeasured",
                "output": str(args.output),
            }
        )
    )


if __name__ == "__main__":
    main()
