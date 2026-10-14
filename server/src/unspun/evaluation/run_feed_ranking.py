"""Compare M3-B ranks without network, database writes or model calls."""

import argparse
import json
from pathlib import Path
from typing import Any, cast

from unspun.evaluation.feed_suite import evaluate_suite


def _read_document(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text())
    if not isinstance(document, dict):
        raise ValueError("input must be a JSON object")
    return cast("dict[str, Any]", document)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--annotations", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--draft", action="store_true", help="Write a review report without passing it"
    )
    args = parser.parse_args(argv)
    output: Path = args.output
    snapshot_path: Path = args.snapshot
    annotations_path: Path = args.annotations
    if output.resolve() in {snapshot_path.resolve(), annotations_path.resolve()}:
        parser.error("report output must not overwrite evaluation inputs")
    try:
        report = evaluate_suite(_read_document(snapshot_path), _read_document(annotations_path))
    except (OSError, ValueError, TypeError) as error:
        report = {"ready": False, "passed": False, "readiness_issues": [str(error)]}
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2) + "\n")
        print("Ranking evaluation input failed; report written.")
        return 2
    if args.draft:
        report["passed"] = False
        report["draft"] = True
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(
        f"events={report.get('event_count', 0)} ready={report['ready']} "
        f"passed={report['passed']} issues={len(report['readiness_issues'])}"
    )
    return 0 if args.draft or report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
