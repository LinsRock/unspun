"""Read-only CL-01 runtime/settings boundary; exports no credentials."""

import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path

from unspun.core.config import get_settings
from unspun.core.sources import load_sources
from unspun.pipeline.r1_runtime import build_runtime

settings = get_settings()
values = settings.model_dump()
selected = {
    k: v
    for k, v in values.items()
    if any(word in k for word in ("model", "budget", "limit", "allocation", "r1_worker"))
    and not any(word in k for word in ("key", "secret", "token", "url"))
}
print(
    json.dumps(
        {
            "captured_at": datetime.now(UTC).isoformat(),
            "app_version": settings.app_version,
            "settings": selected,
            "runtime": build_runtime(load_sources(), settings).describe(),
            "retired_module_present": {
                module: importlib.util.find_spec("unspun.pipeline." + module) is not None
                for module in ("main", "fetcher")
            },
            "fixture_directory_present": Path("/fixtures").exists(),
        },
        indent=2,
        default=str,
    )
)
