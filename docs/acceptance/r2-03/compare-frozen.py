import hashlib
import json
import subprocess
import sys
import types
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from unspun.core.config import get_settings
from unspun.core.content_feed import rank, reviewed, rules
from unspun.core.content_reading import ContentInput
from unspun.core.models import (
    Article,
    ContentDerivation,
    ContentMaterial,
    ContentObservation,
)
from unspun.core.sources import Source
from unspun.pipeline.content_processing import processing_fingerprint

root = Path.cwd().parent
settings = get_settings()
assert settings.database_url.endswith("/unspun_r2_detail_tests_20261020")
freeze = json.loads((root / "docs/evaluations/r2/freeze-v1.json").read_text())
checks = []
for f in freeze["files"]:
    raw = (
        subprocess.check_output(["git", "show", freeze["base_revision"] + ":" + f["path"]])
        if f["path"] == "config/sources.yml"
        else (root / f["path"]).read_bytes()
    )
    assert hashlib.sha256(raw).hexdigest() == f["sha256"], f["path"]
    checks.append(f["path"])
inputs = json.loads((root / "docs/evaluations/r2/inputs-v1.json").read_text())["candidates"]
baseline = json.loads((root / "docs/acceptance/r2-01/production.json").read_text())
sources = [Source.model_validate(x) for x in baseline["sources"]]
at = datetime.fromisoformat(baseline["publication"]["as_of"])
old = types.ModuleType("r2_03_frozen_old")
sys.modules[old.__name__] = old
# Execute only the fixed, trusted repository baseline for a before/after comparison.
exec(  # noqa: S102
    compile(
        subprocess.check_output(
            ["git", "show", "3a67836:server/src/unspun/core/content_feed.py"], text=True
        ),
        "<main-content-feed>",
        "exec",
    ),
    old.__dict__,
)
engine = create_engine(settings.database_url)
with engine.connect() as conn, conn.begin() as tx, Session(bind=conn) as session:
    identities = set()
    for value in inputs:
        content = ContentInput.model_validate(value["input"])
        identities.add(content.article_id)
        assert processing_fingerprint(content, "card") == value["card_processing_fingerprint"]
        original = next(a for a in baseline["articles"] if a["id"] == content.article_id)
        article = Article(
            id=content.article_id,
            source_id=content.source_id,
            title=content.title,
            url=original["url"],
            processing_track="r1",
            r1_metadata={
                "title": content.title,
                **content.metadata.model_dump(mode="json"),
            },
            metadata_fingerprint=content.metadata_fingerprint,
        )
        session.add(article)
        session.flush()
        original_m = next(m for m in baseline["materials"] if m["id"] == content.material_id)
        material = ContentMaterial(
            id=content.material_id,
            article_id=content.article_id,
            input_fingerprint=content.material_fingerprint,
            metadata_fingerprint=content.metadata_fingerprint,
            extractor_version=content.extractor_version,
            schema_version="r1-material-v1",
            scope=content.scope,
            access_status=original_m["access_status"],
            completeness=original_m["completeness"],
            completeness_basis=original_m["completeness_basis"],
            source_url=original_m["source_url"],
            retrieved_at=content.material_observed_at,
            paragraphs=[p.model_dump() for p in content.paragraphs],
            evidence={},
        )
        session.add(material)
        session.flush()
        article.current_material_id = material.id
        session.flush()
    for original in baseline["derivations"]:
        if original["article_id"] in identities and original["material_id"] in {
            v["input"]["material_id"] for v in inputs
        }:
            values = dict(original)
            for key in ("created_at", "updated_at"):
                values[key] = datetime.fromisoformat(values[key])
            session.add(ContentDerivation(**values))
    for original in baseline["observations"]:
        if original["article_id"] in identities:
            session.add(
                ContentObservation(
                    id=original["id"],
                    article_id=original["article_id"],
                    source_id=original["source_id"],
                    item_key=original["item_key"],
                    observation_fingerprint=original["observation_fingerprint"],
                    observed_at=datetime.fromisoformat(original["observed_at"]),
                    discovered_url="https://example.org/frozen-observation",
                    metadata_snapshot={},
                    rank=original["rank"],
                    signals=original["signals"],
                )
            )
    session.flush()
    before = old.reviewed(session, preview=False, as_of=at, sources=sources, policy=rules())
    after = reviewed(session, preview=False, as_of=at, sources=sources, policy=rules())
    report = {
        "schema_version": "r2-candidate-comparison-v3",
        "checked_at": datetime.now(UTC).isoformat(),
        "base_revision": "3a67836",
        "as_of": at.isoformat(),
        "input_source": "inputs-v1.json plus pinned production derivations and source policy",
        "preference_context": (
            "Same empty interests/feedback for both replays; baseline reader "
            "preference rows were not fully captured, so this is not a replay "
            "of all original production ranking scores."
        ),
        "frozen_files_verified": len(checks),
        "fingerprints_verified": len(inputs),
        "regression_inputs": sum(i["split"] == "regression" for i in inputs),
        "holdout_inputs": sum(i["split"] == "holdout" for i in inputs),
        "holdout_use": "Contract/unchanged-rule verification only, no tuning.",
        "material_scope": (
            "Thirty pinned current material versions; historical derivations "
            "referencing unselected older materials are excluded equally from both replays."
        ),
        "before_published_ids": [i.article.id for i in before],
        "after_published_ids": [i.article.id for i in after],
        "orders": {},
        "paid_calls": 0,
        "user_ratings_written": 0,
    }
    for sort in ("recommended", "latest"):
        b, _ = old.rank(session, before, at, sort, rules())
        a, _ = rank(session, after, at, sort, rules())
        bov = [[i.article.id, p] for i, p in b]
        aov = [[i.article.id, p] for i, p in a]
        report["orders"][sort] = {
            "before_ids": [i.article.id for i, _ in b],
            "after_ids": [i.article.id for i, _ in a],
            "same_order_and_scores": bov == aov,
        }
    assert report["before_published_ids"] == report["after_published_ids"]
    assert all(o["same_order_and_scores"] for o in report["orders"].values())
    tx.rollback()
(root / "docs/evaluations/r2/candidate-comparison-v3.json").write_text(
    json.dumps(report, ensure_ascii=False, indent=2) + "\n"
)
print(json.dumps(report, ensure_ascii=False, indent=2))
