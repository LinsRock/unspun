"""Isolated, budgeted live model comparisons; never run on the production DB."""

import argparse
import json
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from threading import Lock
from typing import Any

from pydantic import HttpUrl
from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from unspun.core.config import get_settings
from unspun.core.db import get_engine
from unspun.core.grounding import SUMMARY_VERSION
from unspun.core.llm import LlmClient, LlmError
from unspun.core.models import Article, Event, LlmUsage
from unspun.core.params import get_scoring_params
from unspun.core.sources import Source
from unspun.evaluation import baseline
from unspun.evaluation.quality import CASE_PATH, evaluate_output, load_cases
from unspun.pipeline.summarize import summarize_article
from unspun.pipeline.viewpoints import VIEWPOINT_VERSION, refresh_event_viewpoint


class BudgetExceeded(RuntimeError):
    pass


class BudgetLedger:
    def __init__(self, budget_usd: float, max_calls: int) -> None:
        if budget_usd <= 0 or max_calls <= 0:
            raise ValueError("budget and call cap must be positive")
        self.cost_usd = 0.0
        self.calls = 0
        self._budget = budget_usd
        self._max_calls = max_calls
        self._lock = Lock()

    def reserve(self) -> None:
        with self._lock:
            if self.cost_usd >= self._budget or self.calls >= self._max_calls:
                raise BudgetExceeded("evaluation budget or call cap reached")
            self.calls += 1

    def charge(self, cost: float, actual_calls: int) -> None:
        with self._lock:
            self.cost_usd += cost
            self.calls += max(0, actual_calls - 1)


class BudgetedClient:
    def __init__(self, ledger: BudgetLedger) -> None:
        self.ledger = ledger
        self.client = LlmClient()

    def chat_json(
        self,
        session: Session,
        *,
        model: str,
        system: str,
        user: str,
        purpose: str,
        max_tokens: int = 1024,
    ) -> dict[str, Any]:
        self.ledger.reserve()
        previous = {id(item) for item in session.new}
        try:
            return self.client.chat_json(
                session,
                model=model,
                system=system,
                user=user,
                purpose=purpose,
                max_tokens=max_tokens,
            )
        finally:
            usage = [
                item
                for item in session.new
                if id(item) not in previous and isinstance(item, LlmUsage)
            ]
            self.ledger.charge(sum(item.cost_usd for item in usage), len(usage))
            # Only usage rows are attached to this session. Evaluation articles
            # and events are transient and never stored in the application DB.
            session.commit()

    def embed(self, session: Session, texts: list[str]) -> list[list[float]]:
        raise LlmError("quality evaluation does not perform embeddings")


def require_isolated_database() -> None:
    url = make_url(get_settings().database_url)
    if url.host not in ("localhost", "127.0.0.1") or not str(url.database).startswith(
        "unspun_quality_"
    ):
        raise ValueError("live evaluation requires a local unspun_quality_* database")


def load_key_from_ssh(host: str) -> None:
    if not re.fullmatch(r"[a-zA-Z0-9_.-]+", host):
        raise ValueError("invalid SSH host alias")
    # Capture directly in memory; never echo, log, or persist the credential.
    command = (
        "cd ~/unspun && docker compose -f deploy/compose.yml -f deploy/compose.prod.yml "
        "exec -T worker python -c "
        "'from unspun.core.config import get_settings; print(get_settings().openrouter_api_key)'"
    )
    result = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", host, command],
        capture_output=True,
        check=True,
        text=True,
        timeout=30,
    )
    key = result.stdout.strip()
    if not key or "\n" in key:
        raise ValueError("SSH credential source returned no single credential")
    get_settings().openrouter_api_key = key


def run_case(case: dict[str, Any], variant: str, ledger: BudgetLedger) -> dict[str, Any]:
    articles = [
        Article(
            id=a["id"],
            title=a["title"],
            content=a["content"],
            source_id=a["source_id"],
            url=a["url"],
            lang=a["lang"],
            published_at=datetime.fromisoformat(a["published_at"]),
        )
        for a in case["articles"]
    ]
    sources = {
        a["source_id"]: Source(
            id=a["source_id"],
            name=a["source_name"],
            url=HttpUrl("https://example.com/rss"),
            weight=0.9,
            region=a["region"],
            kind=a["kind"],
            lang=a["lang"],
        )
        for a in case["articles"]
    }
    output: dict[str, Any]
    result: dict[str, Any]
    client = BudgetedClient(ledger)
    settings = get_settings()
    try:
        with Session(get_engine()) as session:
            for article in articles:
                if variant == "candidate":
                    summarize_article(session, client, article)
                else:
                    out = client.chat_json(
                        session,
                        model=settings.summary_model,
                        system=baseline.SUMMARY_SYSTEM,
                        user=(
                            f"Source language: {article.lang}\nTitle: {article.title}\n\n"
                            f"{article.content}"
                        ),
                        purpose="summary",
                    )
                    article.title_zh = str(out.get("title_zh") or article.title)
                    article.summary_zh = str(out.get("summary_zh") or "")
            if variant == "candidate":
                event = Event(title=case["id"], articles=articles)
                status = refresh_event_viewpoint(
                    session,
                    client,
                    event,
                    get_scoring_params().viewpoints,
                    sources,
                )
                output = (
                    event.viewpoint.payload
                    if event.viewpoint
                    else {"claims": [], "disagreements": []}
                )
            else:
                blocks = [
                    f"Event covered by {len(sources)} sources; "
                    f"latest article from each of {len(articles)}:"
                ]
                for article in articles:
                    blocks.append(
                        f"article_id={article.id} [{sources[article.source_id].name}] "
                        f"{article.title_zh}\n"
                        f"  summary: {(article.summary_zh or '')[:500]}\n"
                        f"  lead: {(article.content or '')[:300]}"
                    )
                output = client.chat_json(
                    session,
                    model=settings.viewpoint_model,
                    system=baseline.VIEWPOINT_SYSTEM,
                    user="\n".join(blocks),
                    purpose="viewpoint",
                )
                status = "generated"
            summaries = [
                {
                    "article_id": a.id,
                    "title_zh": a.title_zh,
                    "summary": a.summary_zh,
                    "grounding": a.summary_grounding,
                }
                for a in articles
            ]
            result = {
                "case_id": case["id"],
                "variant": variant,
                "status": status,
                "output": output,
                "metrics": evaluate_output(case, output, summaries),
                "summaries": summaries,
            }
    except Exception as error:
        # Error messages may contain request data. Persist only the class.
        result = {"case_id": case["id"], "variant": variant, "error": type(error).__name__}
    finally:
        client.client.close()
    print(
        json.dumps({"case_id": case["id"], "variant": variant, "completed": "error" not in result}),
        flush=True,
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variant", choices=["baseline", "candidate", "both"], default="both")
    parser.add_argument("--key-source-ssh")
    parser.add_argument("--budget-usd", type=float, default=1.0)
    parser.add_argument("--max-calls", type=int, default=350)
    parser.add_argument("--workers", type=int, choices=[1, 2, 3], default=2)
    parser.add_argument("--case", action="append", dest="case_ids")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    require_isolated_database()
    if args.key_source_ssh:
        load_key_from_ssh(args.key_source_ssh)
    cases = load_cases()
    if args.case_ids:
        cases = [case for case in cases if case["id"] in args.case_ids]
        if {case["id"] for case in cases} != set(args.case_ids):
            raise ValueError("unknown quality case")
    with Session(get_engine()) as session:
        first_usage_id = session.scalar(select(func.coalesce(func.max(LlmUsage.id), 0))) or 0
    ledger = BudgetLedger(args.budget_usd, args.max_calls)
    variants = ["baseline", "candidate"] if args.variant == "both" else [args.variant]
    tasks = [(case, variant) for variant in variants for case in cases]
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [executor.submit(run_case, case, variant, ledger) for case, variant in tasks]
        results = [future.result() for future in futures]
    with Session(get_engine()) as session:
        usage = [
            {
                "purpose": row.purpose,
                "model": row.model,
                "prompt_tokens": row.prompt_tokens,
                "completion_tokens": row.completion_tokens,
                "cost_usd": row.cost_usd,
            }
            for row in session.scalars(
                select(LlmUsage).where(LlmUsage.id > first_usage_id).order_by(LlmUsage.id)
            ).all()
        ]
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "live_model_calls": True,
        "case_suite_version": json.loads(CASE_PATH.read_text())["version"],
        "case_suite_sha256": sha256(CASE_PATH.read_bytes()).hexdigest(),
        "source_tree_sha256_at_report_write": {
            name: sha256((Path(__file__).resolve().parents[1] / name).read_bytes()).hexdigest()
            for name in ("core/grounding.py", "pipeline/summarize.py", "pipeline/viewpoints.py")
        },
        "summary_version": SUMMARY_VERSION,
        "viewpoint_version": VIEWPOINT_VERSION,
        "semantic_entailment_verified": False,
        "budget_usd": args.budget_usd,
        "cost_usd": ledger.cost_usd,
        "calls": ledger.calls,
        "budget_note": "Cap stops subsequent calls; in-flight calls/retries can exceed the cap.",
        "usage_ledger": usage,
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=True, indent=2) + "\n")
    print(
        json.dumps(
            {
                "output": str(args.output),
                "cost_usd": ledger.cost_usd,
                "calls": ledger.calls,
                "cases": len(results),
            }
        )
    )


if __name__ == "__main__":
    main()
