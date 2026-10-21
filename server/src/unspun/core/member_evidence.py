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
                if entry["visible_text"][citation.start : citation.end] != citation.quote:
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
    relation = ("identity", "contribution", "classification", "relation")
    return {
        "query_support": query,
        "anchor_support": anchors,
        "relation": relation,
        "complete_basis": (
            *query,
            *anchors,
            *relation,
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
            classification=decision.classification,
            complete_basis=decision.basis,
        )
    return out


def validate_selection(packet: dict[str, Any], decision: MemberDecision) -> tuple[EvidenceRef, ...]:
    topic = packet["candidate"]["topic"]
    if (
        decision.associated
        and decision.classification in {"same_event", "same_issue"}
        and decision.classification != ("same_event" if topic["kind"] == "event" else "same_issue")
    ):
        raise ValueError("decision does not match the topic kind")
    # Revalidate even programmatic model_copy objects; never admit bypassed validators.
    decision = MemberDecision.model_validate(decision.model_dump(mode="json"))
    if decision.associated and not (decision.query_facts and decision.anchor_facts):
        raise ValueError("association requires both evidence owners")
    for indices, facts in (
        (decision.relation.query_fact_indices, decision.query_facts),
        (decision.relation.anchor_fact_indices, decision.anchor_facts),
    ):
        if len(indices) != len(set(indices)) or any(i >= len(facts) for i in indices):
            raise ValueError("relation refers to absent or duplicate fact indices")
        if decision.associated and not indices:
            raise ValueError("associated relation requires both fact owners")
    if decision.associated:
        reason = {
            "same_event": "same_occurrence",
            "same_issue": "same_issue",
            "background": "context",
            "opinion": "assessment",
            "explanation": "explanation",
            "reprint": "provenance",
        }[decision.classification]
        if decision.relation.reason != reason:
            raise ValueError("relation reason differs from contribution projection")
        for indices, facts in (
            (decision.relation.query_fact_indices, decision.query_facts),
            (decision.relation.anchor_fact_indices, decision.anchor_facts),
        ):
            selected = [facts[i] for i in indices]
            if decision.classification == "same_event" and (
                decision.relation.time != "compatible"
                or any(f.time.status == "conflict" for f in facts)
                or not any(
                    f.time.status == "known" and f.time.role == "occurrence" for f in selected
                )
                or any(
                    not any(getattr(f, role).status == "known" for f in selected)
                    for role in ("subject", "action", "object")
                )
            ):
                raise ValueError(
                    "same_event requires supported identity and compatible occurrence time"
                )
            if decision.classification == "reprint" and not any(
                f.attribution.status == "known" for f in selected
            ):
                raise ValueError("reprint requires provenance from both owners")
    return expanded_evidence(packet, decision)
