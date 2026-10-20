"""Replay the registered four-route comparison offline against the current card input contract."""

import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

import httpx

from unspun.core.content import fingerprint
from unspun.core.content_reading import CARD_VERSION, ContentInput, cheap_exclusion
from unspun.core.sources import Source
from unspun.pipeline.content_processing import processing_fingerprint
from unspun.pipeline.discovery import MATERIAL_VERSION, discover
from unspun.pipeline.materials import body_identity, retrieve_material

archive = Path(sys.argv[1])
production = json.loads(Path(sys.argv[2]).read_text())
rows = []
for record_path in sorted(archive.glob("*/record.json")):
    previous = json.loads(record_path.read_text())
    folder = record_path.parent
    responses = {row["url"]: row for row in previous["http_requests"]}
    redirect_targets = {
        row["url"]: following["url"]
        for row, following in zip(previous["http_requests"], previous["http_requests"][1:])
        if row.get("status") in {301, 302, 303, 307, 308}
    }
    used = []

    def respond(request):
        row = responses[str(request.url)]  # Unknown URLs fail instead of reaching the network.
        used.append(str(request.url))
        body = (folder / row["private_response"]).read_bytes()
        assert hashlib.sha256(body).hexdigest() == row["response_sha256"]
        headers = dict(row["headers"])
        if str(request.url) in redirect_targets:
            # v1 did not archive Location. Reconstruct only the observed next hop.
            headers["location"] = redirect_targets[str(request.url)]
        return httpx.Response(row["status"], content=body, headers=headers)

    source = Source.model_validate(previous["source_contract"])
    observed = datetime.fromisoformat(previous["started_at"])
    result = {
        "source_id": source.id,
        "external_http_requests": 0,
        "materials": [],
        "redirect_targets_reconstructed_from_observed_next_request": redirect_targets,
    }
    with httpx.Client(transport=httpx.MockTransport(respond), follow_redirects=True) as client:
        discovered = discover(source, client, now=observed)
        assert [item.identity_value for item in discovered.items] == [
            item["identity_value"] for item in previous["items"]
        ]
        result["identities_matched"] = len(discovered.items)
        for index, item in enumerate(discovered.items[:3]):
            material = retrieve_material(
                source,
                {
                    "url": str(item.url),
                    "metadata": {"title": item.title, **item.metadata.model_dump(mode="json")},
                    "provided_text": item.provided_text,
                    "provided_truncated": item.provided_truncated,
                    "source_excerpt": item.source_excerpt,
                },
                client,
                now=observed,
            )
            old = json.loads((folder / f"material-{index:02d}.json").read_text())
            actual = material.model_dump(mode="json")
            assert actual["paragraphs"] == old["paragraphs"]
            assert (material.scope, material.access_status) == (old["scope"], old["access_status"])
            metadata = {"title": material.title, **material.metadata.model_dump(mode="json")}
            semantic = body_identity("\n".join(unit.text for unit in material.paragraphs))
            material_fp = fingerprint(
                [
                    MATERIAL_VERSION,
                    material.scope,
                    material.access_status,
                    material.completeness,
                    semantic,
                    metadata,
                ]
            )
            content = ContentInput.model_validate(
                {
                    "article_id": -(len(rows) * 3 + index + 1),
                    "material_id": -(len(rows) * 3 + index + 1),
                    "source_id": source.id,
                    "title": material.title,
                    "metadata": material.metadata,
                    "scope": material.scope,
                    "paragraphs": material.paragraphs,
                    "material_fingerprint": material_fp,
                    "metadata_fingerprint": fingerprint(metadata),
                    "extractor_version": MATERIAL_VERSION,
                    "material_observed_at": material.retrieved_at,
                }
            )
            body_fp = fingerprint(semantic) if semantic else None
            result["materials"].append(
                {
                    "identity": item.identity_value,
                    "url": str(item.url),
                    "title": item.title,
                    "scope": content.scope,
                    "access_status": material.access_status,
                    "characters": len(content.text()),
                    "metadata": material.metadata.model_dump(mode="json"),
                    "metadata_changed_from_first_probe": actual["metadata"] != old["metadata"],
                    "body_and_scope_match_original_response": True,
                    "current_card_input_valid": True,
                    "cheap_exclusion": cheap_exclusion(content, observed),
                    "processing_fingerprint": processing_fingerprint(content, "card"),
                    "exact_body_matches_in_production": [
                        a["id"]
                        for a in production["articles"]
                        if body_fp
                        and a["text_fingerprint"] == body_fp
                        and a["scope"] == material.scope
                    ],
                    "transient_negative_ids_are_not_database_ids": True,
                }
            )
    result["archived_http_responses_used"] = len(used)
    rows.append(result)
print(
    json.dumps(
        {
            "schema_version": "r2-04-current-contract-replay-v1",
            "contract": CARD_VERSION,
            "source_records": rows,
            "model_generation_validated": False,
            "generation_missing_reason": "Observation window and critical-field audit are incomplete; paid gate remains closed.",
            "model_requests": 0,
            "database_writes": 0,
            "synthetic_admissions_created": 0,
        },
        ensure_ascii=False,
        indent=2,
    )
)
