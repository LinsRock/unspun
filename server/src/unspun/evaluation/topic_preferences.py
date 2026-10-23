"""Same exposed R2-08 materials, explicit offline topic states, zero external calls.

Mock topics only enter the pure ranker, never the publication API. Persistence,
CAS and eligibility are independently exercised by the integration tests.
"""

import argparse
import gzip
import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from unspun.core.config import get_settings
from unspun.core.content import fingerprint
from unspun.core.content_feed import rules
from unspun.core.hybrid_contracts import HybridRules
from unspun.core.hybrid_ranking import Candidate, ordered, topic_preference_score
from unspun.core.hybrid_recall import content_candidates
from unspun.core.models import Article
from unspun.core.sources import load_sources
from unspun.evaluation.hybrid_feed import ARTIFACT, AS_OF, ROOT, SHA256
from unspun.evaluation.member_quality import seed_packages


def evaluate(session: Session) -> dict[str, Any]:
    artifact = ROOT / ARTIFACT
    assert hashlib.sha256(artifact.read_bytes()).hexdigest() == SHA256
    assert session.scalar(select(Article.id).limit(1)) is None
    raw: dict[str, Any] = json.loads(gzip.decompress(artifact.read_bytes()))
    seed_packages(session, raw["packages"], material_offset=0)
    policy, reader = HybridRules(), rules()
    contents, _, _ = content_candidates(session, load_sources(), policy, [], AS_OF, AS_OF)
    replay = json.loads((ROOT / "docs/acceptance/r2-07/manual-replay.json").read_text())
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
        {"score": 0},
        lanes=("readable",),
    )
    # Same source/domain control demonstrates that preferences do not spread.
    control = replace(mock, id="engineering-unrelated-topic", title="Unrelated engineering topic")
    scenarios: dict[str, Any] = {}
    for name, followed, feedback in (
        ("baseline", False, None),
        ("follow", True, None),
        ("positive", True, "interested"),
        ("negative", True, "not_interested"),
        ("modify_positive", True, "interested"),
        ("revoke_feedback", True, None),
        ("unfollow", False, None),
        ("positive_only", False, "interested"),
        ("negative_only", False, "not_interested"),
        ("revoke_all", False, None),
    ):
        direct = topic_preference_score(followed, feedback, policy, reader)
        target = replace(mock, reasons={**direct, "score": direct["topic_preference_score"]})
        pool = contents + [target, control]
        recommended = ordered(pool, "recommended", policy, reader)
        target_parts = next(parts for c, parts in recommended if c.id == target.id)
        assert target_parts["important"] is target_parts["public_attention"] is None
        scenarios[name] = {
            "recommended": [f"{c.type}:{c.id}" for c, _ in recommended],
            "latest": [f"{c.type}:{c.id}" for c, _ in ordered(pool, "latest", policy, reader)],
            "target_reasons": target_parts,
            "other_base_scores": {
                f"{c.type}:{c.id}": c.reasons["score"] for c in pool if c.id != target.id
            },
        }
    base = scenarios["baseline"]
    assert all(s["latest"] == base["latest"] for s in scenarios.values())
    assert all(s["other_base_scores"] == base["other_base_scores"] for s in scenarios.values())
    assert scenarios["revoke_all"] == base
    assert len({tuple(s["recommended"]) for s in scenarios.values()}) > 1
    return {
        "contract": "r2-topic-preferences-v1",
        "as_of": AS_OF.isoformat(),
        "material_file": ARTIFACT,
        "sha256": SHA256,
        "reviewer": "Codex engineering comparison; no human quality rating",
        "candidates": [
            {"type": c.type, "id": c.id, "version": c.version, "time": c.time}
            for c in contents + [mock, control]
        ],
        "qualified_content_count": len(contents),
        "topic_provenance": (
            "retained R2-07 ineligible mock and named engineering control; pure ranker only"
        ),
        "scenarios": scenarios,
        "latest_unchanged": True,
        "other_base_scores_unchanged": True,
        "generation": 0,
        "embedding": 0,
        "paid_retries": 0,
        "provider_queries": 0,
        "production_writes": 0,
        "isolated_writes_rolled_back": True,
        "real_topic_quality": "unmeasured",
        "user_acceptance": None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    url = make_url(get_settings().database_url)
    if url.host not in {"localhost", "127.0.0.1", "::1"} or not (url.database or "").startswith(
        "unspun_r209_"
    ):
        parser.error("only an explicit loopback unspun_r209_* database is allowed")
    if args.output.exists():
        parser.error("output exists; retain previous evidence")
    with Session(create_engine(url)) as session:
        result = evaluate(session)
        session.rollback()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {
                "qualified_contents": result["qualified_content_count"],
                "scenarios": len(result["scenarios"]),
                "external_calls": 0,
            }
        )
    )


if __name__ == "__main__":
    main()
