"""Pure hybrid ordering and page-local compression; never hides a candidate ID."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from unspun.core.content_feed import ReaderRules
from unspun.core.hybrid_contracts import HybridRules, Kind, Signal


@dataclass
class Candidate:
    type: Kind
    id: str
    version: str
    title: str
    sources: tuple[str, ...]
    domains: tuple[str, ...]
    time: dict[str, Any]
    payload: dict[str, Any]
    reasons: dict[str, Any]
    lanes: tuple[str, ...] = ()
    duplicate_ids: tuple[str, ...] = ()
    unique_ids: tuple[str, ...] = ()
    protect: bool = False
    signals: dict[str, Signal] = field(default_factory=dict[str, Signal])

    @property
    def key(self) -> tuple[str, str]:
        return self.type, self.id


def time_key(value: dict[str, Any]) -> datetime:
    if value.get("precision") == "time" and value.get("at"):
        return datetime.fromisoformat(value["at"]).astimezone(UTC)
    if value.get("precision") == "date" and value.get("on"):
        return datetime.fromisoformat(value["on"]).replace(tzinfo=ZoneInfo("Asia/Shanghai"))
    return datetime.min.replace(tzinfo=UTC)


def ordered(
    candidates: list[Candidate], sort: str, policy: HybridRules, reader: ReaderRules
) -> list[tuple[Candidate, dict[str, Any]]]:
    remaining: list[tuple[Candidate, dict[str, Any]]] = []
    for c in candidates:
        parts = dict(c.reasons)
        parts.update(
            important=c.signals["important"].model_dump(mode="json")
            if "important" in c.signals
            else None,
            public_attention=c.signals["public_attention"].model_dump(mode="json")
            if "public_attention" in c.signals
            else None,
            missing_signals=[k for k in ("important", "public_attention") if k not in c.signals],
            recall_lanes=list(c.lanes),
            importance_boost=policy.importance_weight if "important" in c.signals else 0,
            attention_boost=policy.attention_weight if "public_attention" in c.signals else 0,
            diversity=0.0,
        )
        parts["score"] = c.reasons["score"] + parts["importance_boost"] + parts["attention_boost"]
        remaining.append((c, parts))
    if sort == "latest":
        return sorted(remaining, key=lambda p: (time_key(p[0].time), p[0].key), reverse=True)
    result: list[tuple[Candidate, dict[str, Any]]] = []
    while remaining:
        history = result[-(reader.source_window - 1) :] if reader.source_window > 1 else []
        for c, parts in remaining:
            source_count = max(
                (sum(s in h.sources for h, _ in history) for s in c.sources), default=0
            )
            domain_count = sum(c.domains[:1] == h.domains[:1] for h, _ in history)
            parts["diversity"] = -(
                (reader.source_penalty if source_count >= reader.source_soft_limit else 0)
                + (reader.domain_penalty if domain_count >= reader.domain_soft_limit else 0)
            )
        best = max(
            range(len(remaining)),
            key=lambda i: (
                remaining[i][1]["score"] + remaining[i][1]["diversity"],
                time_key(remaining[i][0].time),
                remaining[i][0].key,
            ),
        )
        c, parts = remaining.pop(best)
        parts["total_score"] = parts["score"] + parts["diversity"]
        result.append((c, parts))
    return result


def render_page(rows: list[tuple[Candidate, dict[str, Any]]]) -> list[dict[str, Any]]:
    topics = [c for c, _ in rows if c.type == "topic"]
    unique_ids = {identity for t in topics for identity in t.unique_ids}
    output: list[dict[str, Any]] = []
    for c, parts in rows:
        refs = [t.id for t in topics if c.id in t.duplicate_ids] if c.type == "content" else []
        compress = bool(refs) and not c.protect and c.id not in unique_ids
        payload = dict(c.payload)
        if compress:
            # Keep identity, metadata and original URL. Only the repeated card body is omitted.
            payload.pop("card", None)
        output.append(
            {
                "type": c.type,
                "id": c.id,
                "version": c.version,
                "title": c.title,
                "time": c.time,
                "presentation": "reference" if compress else "full",
                "reference_to": refs if compress else [],
                "content": payload if c.type == "content" else None,
                "topic": payload if c.type == "topic" else None,
                "ranking": parts,
            }
        )
    return output
