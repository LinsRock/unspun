"""Collect the existing R2-04 window without starting requests or enabling sources."""

import argparse
import hashlib
import json
import subprocess
import tarfile
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    args.private_dir.mkdir(parents=True, exist_ok=False)
    archive = args.private_dir / "window.tar.gz"
    with archive.open("xb") as handle:
        subprocess.run(
            [
                "ssh",
                "unspun",
                "tar -C /home/leon/unspun-observations/r2-04-window-v1 -czf - window",
            ],
            stdout=handle,
            check=True,
            timeout=60,
        )
    with tarfile.open(archive) as handle:
        handle.extractall(args.private_dir, filter="data")
    root = args.private_dir / "window"
    run = json.loads((root / "run.json").read_text())
    records = [json.loads(p.read_text()) for p in sorted(root.glob("*/record.json"))]
    captured = datetime.now(UTC)
    result = {
        "schema_version": "r2-04-window-progress-v1",
        "collected_at": captured.isoformat(),
        "run": run,
        "private_archive": str(archive),
        "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "container_state": subprocess.check_output(
            [
                "ssh",
                "unspun",
                "docker inspect unspun-r204-window-v1 --format '{{.State.Status}} {{.State.ExitCode}}'",
            ],
            text=True,
            timeout=30,
        ).strip(),
        "collection_starts_source_requests": False,
        "window_finished": (root / "finished.json").exists(),
        "interrupted": json.loads((root / "interrupted.json").read_text())
        if (root / "interrupted.json").exists()
        else None,
        "sources": {},
        "records": records,
    }
    started = datetime.fromisoformat(run["started_at"])
    for source_id in run["source_ids"]:
        samples = sorted(
            (r for r in records if r["source_id"] == source_id),
            key=lambda r: r["round_index"],
        )
        seen = set()
        new = []
        supported_new = []
        repeats = 0
        material_urls = set()
        materials = []
        streak = maximum_streak = 0
        last_failure = -1
        for index, record in enumerate(samples):
            if record["status"] != "ok":
                streak += 1
                maximum_streak = max(maximum_streak, streak)
                last_failure = index
            else:
                streak = 0
            for item in record.get("items", []):
                identity = (item["identity_namespace"], item["identity_value"])
                if identity in seen:
                    repeats += 1
                elif index:
                    new.append(
                        {
                            "identity": identity,
                            "url": item["url"],
                            "title": item["title"],
                            "times": item["metadata"]["times"],
                        }
                    )
                    for at in item["metadata"]["times"]:
                        if (
                            at["at"]
                            and at["kind"] in {"original", "feed"}
                            and started
                            <= datetime.fromisoformat(at["at"])
                            <= datetime.fromisoformat(record["completed_at"])
                        ):
                            supported_new.append(identity)
                            break
                seen.add(identity)
            for material in record.get("materials", []):
                material_urls.add(material["url"])
                materials.append(material)
        successes = sum(r["status"] == "ok" for r in samples)
        material_successes = sum(
            m.get("material", {}).get("access_status") == "ok"
            and m.get("material", {}).get("scope")
            == (
                "complete_brief"
                if source_id == "36kr-newsflashes"
                else "open_text_unit"
            )
            and m.get("characters", 0) > 0
            for m in materials
        )
        times = [datetime.fromisoformat(r["started_at"]) for r in samples]
        elapsed = (times[-1] - times[0]).total_seconds() if len(times) > 1 else 0
        days = sorted(
            {t.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat() for t in times}
        )
        gaps = [(b - a).total_seconds() for a, b in zip(times, times[1:])]
        missing = sorted(
            set(range(max((r["round_index"] for r in samples), default=-1) + 1))
            - {r["round_index"] for r in samples}
        )
        result["sources"][source_id] = {
            "scheduled_rounds_planned": 21,
            "recorded_rounds": len(samples),
            "metadata_successes": successes,
            "metadata_failures": len(samples) - successes,
            "metadata_success_fraction": successes / len(samples) if samples else None,
            "maximum_consecutive_metadata_failures": maximum_streak,
            "successes_after_last_failure": len(samples) - 1 - last_failure
            if last_failure >= 0
            else None,
            "elapsed_seconds": elapsed,
            "local_dates": days,
            "maximum_gap_seconds": max(gaps, default=0),
            "missing_round_indices_before_latest": missing,
            "sampled_materials": len(materials),
            "declared_scope_successes": material_successes,
            "declared_scope_success_fraction": material_successes / len(materials)
            if materials
            else None,
            "distinct_material_urls": len(material_urls),
            "distinct_list_identities": len(seen),
            "repeated_list_observations": repeats,
            "new_identities_after_round_zero": new,
            "new_identities_with_supported_platform_or_brief_time_inside_window": supported_new,
            "client_http_attempts_including_redirects": sum(
                len(r["http_requests"]) for r in samples
            ),
            "numeric_window_complete": len(samples) >= 13
            and elapsed >= 21600
            and len(days) >= 2
            and not missing,
            "critical_identity_author_time_scope_audit": "pending; never infer zero errors from HTTP success",
            "g2_pass": False,
            "paid_allowed": False,
            "published_new_readable_items": 0,
        }
    with args.report.open("x") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(
        json.dumps(
            {
                "report": str(args.report),
                "sources": {
                    k: {
                        a: b
                        for a, b in v.items()
                        if a
                        not in {
                            "new_identities_after_round_zero",
                            "new_identities_with_supported_platform_or_brief_time_inside_window",
                        }
                    }
                    for k, v in result["sources"].items()
                },
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
