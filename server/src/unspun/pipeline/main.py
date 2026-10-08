"""Pipeline worker entry point.

M0 placeholder: the real fetch/summarize/cluster/score pipeline lands in M1.
Runs an idle loop so the worker container stays healthy under compose.
"""

import time

from unspun.core.logging import configure_logging, get_logger


def main() -> None:
    configure_logging()
    log = get_logger("unspun.pipeline")
    log.info("pipeline_worker_started", mode="idle")
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
