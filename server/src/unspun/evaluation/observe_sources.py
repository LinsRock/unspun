"""Read-only R1 probes: no application DB, task creation, model, or publication."""

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from unspun.core.content import fingerprint
from unspun.core.sources import Source, load_sources
from unspun.pipeline.discovery import discover
from unspun.pipeline.feeds import make_client
from unspun.pipeline.materials import retrieve_material


def observe(source: Source, *, sample_items: int = 2, sample_offset: int = 0) -> dict[str, Any]:
    started = datetime.now(UTC)
    result: dict[str, Any] = {
        "version": "r1-source-observation-v1",
        "source_id": source.id,
        "source_url": str(source.url),
        "source_contract": source.r1.model_dump(mode="json") if source.r1 else None,
        "started_at": started.isoformat(),
        "paid_requests": 0,
        "database_writes": 0,
    }
    try:
        with make_client() as client:
            discovery = discover(source, client)
            result.update(
                status="ok",
                response_fingerprint=discovery.response_fingerprint,
                item_count=len(discovery.items),
                items=[
                    item.model_dump(mode="json", exclude={"provided_text"})
                    for item in discovery.items
                ],
            )
            materials: list[dict[str, Any]] = []
            offset = sample_offset % len(discovery.items)
            selected = discovery.items[offset:] + discovery.items[:offset]
            for item in selected[:sample_items]:
                metadata = {"title": item.title, **item.metadata.model_dump(mode="json")}
                material = retrieve_material(
                    source,
                    {
                        "url": str(item.url),
                        "metadata": metadata,
                        "provided_text": item.provided_text,
                        "provided_truncated": item.provided_truncated,
                        "source_excerpt": item.source_excerpt,
                    },
                    client,
                )
                record = material.model_dump(mode="json", exclude={"paragraphs"})
                record.update(
                    text_fingerprint=fingerprint(
                        [unit.model_dump() for unit in material.paragraphs]
                    ),
                    character_count=sum(len(unit.text) for unit in material.paragraphs),
                    paragraph_samples=[unit.text[:160] for unit in material.paragraphs[:3]],
                )
                materials.append(record)
            result["materials"] = materials
    except Exception as error:
        result.update(status="error", error_kind=type(error).__name__)
    result["completed_at"] = datetime.now(UTC).isoformat()
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", action="append", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--rounds", type=int, default=1)
    parser.add_argument("--interval-seconds", type=int, default=1800)
    parser.add_argument("--sample-items", type=int, default=2)
    args = parser.parse_args()
    if not 1 <= args.rounds <= 100 or args.interval_seconds < 60 or not 0 <= args.sample_items <= 3:
        raise ValueError("observation bounds are invalid")
    sources = {source.id: source for source in load_sources()}
    if not set(args.source) <= sources.keys():
        raise ValueError("unknown observation source")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic()
    for index in range(args.rounds):
        with ThreadPoolExecutor(max_workers=2) as executor:
            pending = {
                executor.submit(
                    observe,
                    sources[source_id],
                    sample_items=args.sample_items,
                    sample_offset=index * args.sample_items,
                ): source_id
                for source_id in args.source
            }
            for future in as_completed(pending):
                source_id = pending[future]
                result = future.result()
                name = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ") + "-" + source_id + ".json"
                with (args.output_dir / name).open("x") as handle:
                    json.dump(result, handle, ensure_ascii=False, indent=2)
                    handle.write("\n")
                print(
                    json.dumps(
                        {"source_id": source_id, "status": result["status"], "output": name}
                    ),
                    flush=True,
                )
        if index + 1 < args.rounds:
            deadline += args.interval_seconds
            time.sleep(max(0, deadline - time.monotonic()))


if __name__ == "__main__":
    main()
