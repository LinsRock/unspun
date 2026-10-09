"""Pipeline worker entry point: fetch -> summarize -> embed -> cluster.

Scoring joins this loop as the last M1 stage.
"""

import time

from unspun.core.config import get_settings
from unspun.core.llm import LlmClient
from unspun.core.logging import configure_logging, get_logger
from unspun.pipeline.cluster import cluster_pending
from unspun.pipeline.fetcher import run_fetch_cycle
from unspun.pipeline.summarize import embed_pending, summarize_pending

MIN_SLEEP_SECONDS = 60

log = get_logger("unspun.pipeline")


def run_ai_stages() -> None:
    if not get_settings().openrouter_api_key:
        log.warning("ai_stages_skipped", reason="UNSPUN_OPENROUTER_API_KEY not set")
        return
    with LlmClient() as client:
        summarized = summarize_pending(client)
        embedded = embed_pending(client)
    assigned, created = cluster_pending()
    log.info(
        "ai_stages_finished",
        summarized=summarized,
        embedded=embedded,
        clustered=assigned,
        new_events=created,
    )


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
