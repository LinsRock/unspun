"""Pipeline worker entry point: runs a fetch cycle on a fixed interval.

Summarize/cluster/score stages join this loop as they land in M1.
"""

import time

from unspun.core.config import get_settings
from unspun.core.logging import configure_logging, get_logger
from unspun.pipeline.fetcher import run_fetch_cycle

MIN_SLEEP_SECONDS = 60


def main() -> None:
    configure_logging()
    log = get_logger("unspun.pipeline")
    interval_seconds = get_settings().fetch_interval_minutes * 60
    log.info("pipeline_worker_started", interval_seconds=interval_seconds)
    while True:
        started = time.monotonic()
        try:
            run_fetch_cycle()
        except Exception:
            log.exception("fetch_cycle_failed")
        elapsed = time.monotonic() - started
        time.sleep(max(MIN_SLEEP_SECONDS, interval_seconds - elapsed))


if __name__ == "__main__":
    main()
