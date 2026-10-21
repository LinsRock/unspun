"""Server-owned citation expansion and complete immutable audit coverage."""

from typing import Any, Literal

from unspun.core.content import fingerprint
from unspun.core.member_contracts import (
    AUDIT_KINDS,
    AuditKind,
    MemberAudit,
    MemberAuditContent,
    MemberDecision,
    MemberReview,
    ReviewBinding,
    project_material,
)
from unspun.core.topic_contracts import EvidenceRef


def reference_catalog(packet: dict[str, Any]) -> dict[str, dict[str, Any]]:
    catalog: dict[str, dict[str, Any]] = {}
    materials = [project_material(packet["query"], "query")] + [
        project_material(a["snapshot"], "anchor") for a in packet["candidate"]["topic"]["anchors"]
    ]
    for material in materials:
        content = material["content"]
        for paragraph in content["paragraphs"]:
            for ref in paragraph["references"]:
                value = {
                    "role": material["role"],
                    "article_id": content["article_id"],
                    "material_id": content["material_id"],
                    "paragraph": paragraph["index"],
                    "voice": ref["voice"],
                    "scope": content["scope"],
                    "visible_text": paragraph["text"],
                }
                previous = catalog.setdefault(ref["reference_id"], value)
                if previous != value:
                    raise ValueError("reference identity collision")
    return catalog


def expanded_evidence(packet: dict[str, Any], decision: MemberDecision) -> tuple[EvidenceRef, ...]:
    catalog = reference_catalog(packet)
    refs: list[EvidenceRef] = []
    for role, facts in (("query", decision.query_facts), ("anchor", decision.anchor_facts)):
        for fact in facts:
            for citation in fact.citations:
                entry = catalog.get(citation.reference_id)
                if entry is None:
                    raise ValueError("unknown or stale member reference ID")
                if entry["role"] != role:
                    raise ValueError("fact reference belongs to another role")
                if citation.quote not in entry["visible_text"]:
                    raise ValueError("evidence quote is outside the visible supplied paragraph")
                refs.append(
                    EvidenceRef(
                        **{
                            k: entry[k] for k in ("article_id", "material_id", "paragraph", "voice")
                        },
                        quote=citation.quote,
                    )
                )
    return tuple(refs)


def review_binding(packet: dict[str, Any], decision: MemberDecision) -> ReviewBinding:
    return ReviewBinding(
        decision_fingerprint=fingerprint(decision.model_dump(mode="json")),
        materials_fingerprint=fingerprint(
            {"query": packet["query"], "anchors": packet["candidate"]["topic"]["anchors"]}
        ),
        contract_fingerprint=fingerprint(packet["contract"]),
        references_fingerprint=fingerprint(reference_catalog(packet)),
        packet_fingerprint=fingerprint({k: packet[k] for k in ("query", "candidate", "contract")}),
    )


def audit_targets(decision: MemberDecision, kind: AuditKind) -> tuple[str, ...]:
    query = tuple(f"query_facts/{i}" for i in range(len(decision.query_facts)))
    anchors = tuple(f"anchor_facts/{i}" for i in range(len(decision.anchor_facts)))
    inferences = tuple(f"relation_inferences/{i}" for i in range(len(decision.relation_inferences)))
    return {
        "query_support": query,
        "anchor_support": anchors,
        "relation": ("classification", *inferences),
        "complete_basis": (
            *query,
            *anchors,
            *inferences,
            "basis_complete",
            "attribution",
            "scope",
            "dates",
        ),
    }[kind]


def audit_supported(audit: MemberAudit, binding: ReviewBinding, targets: tuple[str, ...]) -> bool:
    actual = [item.target for item in audit.checks]
    return (
        audit.binding == binding
        and len(actual) == len(set(actual))
        and set(actual) == set(targets)
        and not audit.issues
        and all(item.status == "supported" and not item.issues for item in audit.checks)
    )


def review_supported(
    packet: dict[str, Any], decision: MemberDecision, review: MemberReview
) -> bool:
    binding = review_binding(packet, decision)
    kinds = [audit.kind for audit in review.audits]
    return (
        review.binding == binding
        and tuple(kinds) == AUDIT_KINDS
        and all(
            audit_supported(audit, binding, audit_targets(decision, audit.kind))
            for audit in review.audits
        )
    )


def audit_packet(
    packet: dict[str, Any], decision: MemberDecision, kind: AuditKind
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "kind": kind,
        "targets": audit_targets(decision, kind),
        "output_schema": MemberAuditContent.model_json_schema(),
    }
    if kind in ("query_support", "anchor_support"):
        role: Literal["query", "anchor"] = "query" if kind == "query_support" else "anchor"
        out["materials"] = (
            [project_material(packet["query"], role)]
            if role == "query"
            else [
                project_material(a["snapshot"], role)
                for a in packet["candidate"]["topic"]["anchors"]
            ]
        )
        out["facts"] = [
            f.model_dump(mode="json")
            for f in (decision.query_facts if role == "query" else decision.anchor_facts)
        ]
    else:
        out.update(
            query=project_material(packet["query"], "query"),
            candidate={
                "topic": {
                    **packet["candidate"]["topic"],
                    "anchors": [
                        {**a, "snapshot": project_material(a["snapshot"], "anchor")}
                        for a in packet["candidate"]["topic"]["anchors"]
                    ],
                }
            },
            decision=decision.model_dump(mode="json"),
            complete_basis=decision.basis,
        )
    return out
