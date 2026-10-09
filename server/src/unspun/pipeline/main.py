"""Pipeline worker entry point: fetch -> summarize -> embed -> cluster.

Scoring joins this loop as the last M1 stage.
"""

import time

from unspun.core.config import get_settings
from unspun.core.db import session_scope
from unspun.core.llm import LlmClient
from unspun.core.logging import configure_logging, get_logger
from unspun.core.models import PipelineRun
from unspun.pipeline.cluster import cluster_pending
from unspun.pipeline.fetcher import run_fetch_cycle
from unspun.pipeline.score import score_pending
from unspun.pipeline.summarize import embed_pending, summarize_pending

MIN_SLEEP_SECONDS = 60

log = get_logger("unspun.pipeline")


def run_ai_stages() -> None:
    if not get_settings().openrouter_api_key:
        log.warning("ai_stages_skipped", reason="UNSPUN_OPENROUTER_API_KEY not set")
        return
    counts = {"summarized": 0, "embedded": 0, "clustered": 0, "new_events": 0, "scored": 0}
    try:
        with LlmClient() as client:
            counts["summarized"] = summarize_pending(client)
            counts["embedded"] = embed_pending(client)
            counts["clustered"], counts["new_events"] = cluster_pending()
            counts["scored"] = score_pending(client)
    finally:
        # Record even a partial cycle, so the report's last-run stage counts
        # reflect work that actually happened before a mid-cycle failure.
        with session_scope() as session:
            session.add(PipelineRun(**counts))
        log.info("ai_stages_finished", **counts)


def run_cycle() -> None:
    run_fetch_cycle()
    run_ai_stages()


def main() -> None:
    configure_logging()
    interval_seconds = get_settings().fetch_interval_minutes * 60
    log.info("pipeline_worker_started", interval_seconds=interval_seconds)
    while True:
        started = time.monotonic()
        try:
            run_cycle()
        except Exception:
            log.exception("cycle_failed")
        elapsed = time.monotonic() - started
        time.sleep(max(MIN_SLEEP_SECONDS, interval_seconds - elapsed))


if __name__ == "__main__":
    main()
