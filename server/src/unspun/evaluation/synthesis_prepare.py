"""Prepare a bounded live-quality input packet without tasks, writes or provider calls."""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from unspun.core.content import fingerprint
from unspun.core.db import get_engine
from unspun.core.sources import load_sources
from unspun.core.synthesis_contracts import ManualReview
from unspun.core.topic_synthesis import synthesis_input


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--topic", type=UUID, required=True)
    parser.add_argument("--revision", type=int, required=True)
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--identity", choices=("human", "agent_manual"), required=True)
    parser.add_argument("--basis", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    reviewer = ManualReview.model_validate(
        {"actor": args.reviewer, "identity": args.identity, "basis": args.basis}
    )
    with Session(get_engine()) as session, session.begin():
        session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        packet = synthesis_input(
            session,
            args.topic,
            args.revision,
            reviewer,
            sources=load_sources(),
            now=datetime.now(UTC),
            response_mode="live",
        )
    result = {
        "kind": "unapproved-live-quality-input",
        "packet": packet,
        "input_fingerprint": fingerprint(packet),
        "generation": 0,
        "embedding": 0,
        "paid_retries": 0,
        "database_writes": 0,
        "paid_authorization": False,
        "quality_measured": False,
    }
    with args.output.open("x") as target:
        target.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print("Prepared unapproved input only; no task, provider call or budget change")


if __name__ == "__main__":
    main()
