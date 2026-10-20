"""Bounded R2-04 capture; run only in a credential-free target observation container."""

import argparse
import hashlib
import json
import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from unspun.core.sources import load_sources
from unspun.pipeline.discovery import discover
from unspun.pipeline.feeds import USER_AGENT
from unspun.pipeline.materials import retrieve_material


def stamp():
    return datetime.now(UTC).isoformat()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def write_new(path, value):
    with path.open("x") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


class Capture(httpx.BaseTransport):
    def __init__(self, directory, limit):
        self.inner = httpx.HTTPTransport(retries=0)
        self.directory = directory
        self.limit = limit
        self.requests = []

    def handle_request(self, request):
        if len(self.requests) >= self.limit:
            raise ValueError("registered HTTP request ceiling reached")
        row = {"url": str(request.url), "method": request.method, "started_at": stamp()}
        self.requests.append(row)
        try:
            response = self.inner.handle_request(request)
            try:
                chunks = []
                size = 0
                for chunk in response.iter_raw():
                    size += len(chunk)
                    if size > 2 * 1024 * 1024:
                        raise ValueError("registered response size ceiling reached")
                    chunks.append(chunk)
                data = b"".join(chunks)
                name = f"response-{len(self.requests):02d}.bin"
                (self.directory / name).write_bytes(data)
                row.update(
                    status=response.status_code,
                    response_sha256=digest(data),
                    response_bytes=len(data),
                    private_response=name,
                    headers={
                        key: response.headers[key]
                        for key in (
                            "date",
                            "age",
                            "etag",
                            "last-modified",
                            "content-type",
                        )
                        if key in response.headers
                    },
                )
                return httpx.Response(
                    response.status_code,
                    headers=response.headers,
                    content=data,
                    request=request,
                )
            finally:
                response.close()
        except Exception as error:
            row.update(error_kind=type(error).__name__, error=str(error))
            raise
        finally:
            row["completed_at"] = stamp()
            write_new(self.directory / f"request-{len(self.requests):02d}.json", row)

    def close(self):
        self.inner.close()


def capture(source, directory, *, samples, offset, limit, scheduled_at, round_index):
    directory.mkdir(parents=True, exist_ok=False)
    record = {
        "version": "r2-04-observation-v1",
        "source_id": source.id,
        "source_url": str(source.url),
        "source_contract": source.model_dump(mode="json"),
        "scheduled_at": scheduled_at.isoformat(),
        "round_index": round_index,
        "started_at": stamp(),
        "paid_requests": 0,
        "database_writes": 0,
        "materials": [],
    }
    transport = Capture(directory, limit)
    try:
        with httpx.Client(
            transport=transport,
            timeout=20,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"},
        ) as client:
            result = discover(source, client)
            record.update(
                status="ok",
                response_fingerprint=result.response_fingerprint,
                scan_counts=result.scan_counts,
                items=[
                    item.model_dump(mode="json", exclude={"provided_text"})
                    for item in result.items
                ],
                item_count=len(result.items),
            )
            if not result.items:
                raise ValueError("empty discovery cannot pass metadata gate")
            start = offset % len(result.items)
            selected = (result.items[start:] + result.items[:start])[:samples]
            for index, item in enumerate(selected):
                sample = {
                    "item_key": item.item_key,
                    "url": str(item.url),
                    "started_at": stamp(),
                }
                record["materials"].append(sample)
                try:
                    material = retrieve_material(
                        source,
                        {
                            "url": str(item.url),
                            "metadata": {
                                "title": item.title,
                                **item.metadata.model_dump(mode="json"),
                            },
                            "provided_text": item.provided_text,
                            "provided_truncated": item.provided_truncated,
                            "source_excerpt": item.source_excerpt,
                        },
                        client,
                    )
                    full = material.model_dump(mode="json")
                    write_new(directory / f"material-{index:02d}.json", full)
                    sample.update(
                        status="ok",
                        material={k: v for k, v in full.items() if k != "paragraphs"},
                        text_sha256=digest(
                            json.dumps(
                                full["paragraphs"], ensure_ascii=False, sort_keys=True
                            ).encode()
                        ),
                        characters=sum(len(unit.text) for unit in material.paragraphs),
                        excerpts=[unit.text[:160] for unit in material.paragraphs[:3]],
                    )
                except Exception as error:
                    sample.update(
                        status="error",
                        error_kind=type(error).__name__,
                        error=str(error),
                    )
                sample["completed_at"] = stamp()
    except Exception as error:
        record.update(status="error", error_kind=type(error).__name__, error=str(error))
    record.update(completed_at=stamp(), http_requests=transport.requests)
    write_new(directory / "record.json", record)
    return record


def main():
    if os.environ.get("UNSPUN_OPENROUTER_API_KEY") or os.environ.get(
        "UNSPUN_DATABASE_URL"
    ):
        raise ValueError("observation must not receive database or model credentials")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registration", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--phase", choices=("comparison", "window"), required=True)
    args = parser.parse_args()
    registration = json.loads(args.registration.read_text())
    if args.phase == "comparison":
        source_ids = list(registration["comparison"]["routes"])
        rounds, interval, samples, ceiling = 1, 0, 3, 20
    else:
        source_ids = registration["selected_source_ids"]
        rounds, interval, samples, ceiling = 21, 1800, 2, 13
        if not 1 <= len(source_ids) <= 3:
            raise ValueError("selected route count is outside registration")
    sources = {source.id: source for source in load_sources()}
    args.output.mkdir(parents=True, exist_ok=False)
    start = datetime.now(UTC)
    write_new(
        args.output / "run.json",
        {
            "phase": args.phase,
            "started_at": start.isoformat(),
            "source_ids": source_ids,
            "rounds": rounds,
            "interval_seconds": interval,
            "samples": samples,
            "registration_sha256": digest(args.registration.read_bytes()),
            "script_sha256": digest(Path(__file__).read_bytes()),
            "source_config_sha256": digest(
                Path("/app/config/sources.yml").read_bytes()
            ),
            "paid_requests": 0,
            "database_writes": 0,
        },
    )
    deadline = time.monotonic()
    for index in range(rounds):
        scheduled_at = start + timedelta(seconds=index * interval)
        for source_id in source_ids:
            record = capture(
                sources[source_id],
                args.output / f"{index:03d}-{source_id}",
                samples=samples,
                offset=index * samples,
                limit=ceiling,
                scheduled_at=scheduled_at,
                round_index=index,
            )
            print(
                json.dumps(
                    {"source_id": source_id, "round": index, "status": record["status"]}
                ),
                flush=True,
            )
        if index + 1 < rounds:
            deadline += interval
            # Late wakeups are retained; do not run compressed catch-up requests.
            delay = deadline - time.monotonic()
            if delay < 0:
                write_new(
                    args.output / "interrupted.json",
                    {"at": stamp(), "reason": "scheduled gap exceeded"},
                )
                break
            time.sleep(max(0, delay))
    write_new(args.output / "finished.json", {"at": stamp()})


if __name__ == "__main__":
    main()
