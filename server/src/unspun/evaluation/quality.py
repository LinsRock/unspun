"""Grounding and coverage metrics; quote matching does not establish entailment."""

import json
import re
from pathlib import Path
from typing import Any, cast

from unspun.core.grounding import quote_in_source

CASE_PATH = Path(__file__).resolve().parents[3] / "eval" / "quality_cases.json"


def load_cases(path: Path = CASE_PATH) -> list[dict[str, Any]]:
    document: dict[str, Any] = json.loads(path.read_text())
    return cast("list[dict[str, Any]]", document["cases"])


def evaluate_output(
    case: dict[str, Any],
    output: dict[str, Any],
    summaries: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    articles = {a["id"]: a for a in case["articles"]}
    claims: list[dict[str, Any]] = output.get("claims", [])
    relations: list[dict[str, Any]] = output.get("disagreements", [])
    expected: dict[str, Any] = case["expectations"]
    valid = 0
    ids: list[int] = []
    for claim in claims:
        article = articles.get(claim.get("article_id"))
        if article:
            ids.append(article["id"])
            source = f"{article['title']}\n{article['content']}"
            if quote_in_source(str(claim.get("evidence_quote") or ""), source):
                valid += 1
    text = "\n".join(str(c.get("claim", "")) for c in claims)
    text += "\n" + "\n".join(str(r.get("point", "")) for r in relations)
    missing_facts = [p for p in expected.get("required_patterns", []) if not re.search(p, text)]
    forbidden = [p for p in expected.get("forbidden_patterns", []) if p in text]
    summary_texts = {
        str(row["article_id"]): f"{row.get('title_zh') or ''}\n{row.get('summary') or ''}"
        for row in summaries or []
    }
    summary_text = "\n".join(summary_texts.values())
    summary_forbidden = [p for p in expected.get("forbidden_patterns", []) if p in summary_text]
    summary_missing = (
        [
            f"{article_id}:{pattern}"
            for article_id, patterns in expected.get("summary_required_patterns", {}).items()
            for pattern in patterns
            if not re.search(pattern, summary_texts.get(article_id, ""))
        ]
        if summaries is not None
        else []
    )
    unexpected = [
        r.get("kind") for r in relations if r.get("kind") not in expected["allowed_kinds"]
    ]
    missing = sorted(set(expected.get("required_kinds", [])) - {r.get("kind") for r in relations})
    invalid_relations = sum(
        len(set(indexes := r.get("claim_indexes", []))) < 2
        or any(type(i) is not int or i < 0 or i >= len(claims) for i in indexes)
        for r in relations
    )
    coverage = len(set(ids)) >= expected["min_claims"]
    duplicates = len(ids) != len(set(ids))
    return {
        "claim_count": len(claims),
        "valid_evidence_claims": valid,
        "distinct_sources": len(set(ids)),
        "minimum_coverage_met": coverage,
        "forbidden_assertions": forbidden,
        "summary_forbidden_assertions": summary_forbidden,
        "summary_missing_required_facts": summary_missing,
        "unexpected_kinds": unexpected,
        "invalid_relations": invalid_relations,
        "missing_required_kinds": missing,
        "missing_required_facts": missing_facts,
        "passed": coverage
        and valid == len(claims)
        and not (
            forbidden
            or unexpected
            or invalid_relations
            or duplicates
            or missing
            or missing_facts
            or summary_forbidden
            or summary_missing
        ),
        "semantic_entailment_verified": False,
    }
