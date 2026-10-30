"""Production readers must not need the retired offline generation package."""

import os
import shutil
import subprocess
import sys
from pathlib import Path


def test_runtime_imports_without_offline_tools(tmp_path: Path) -> None:
    source = Path(__file__).resolve().parents[1] / "src" / "unspun"
    shutil.copytree(
        source,
        tmp_path / "unspun",
        ignore=shutil.ignore_patterns("evaluation", "__pycache__"),
    )
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import importlib.util
import sys
from unspun.api.app import app
from unspun.pipeline.r1_runtime import build_runtime

assert importlib.util.find_spec('unspun.evaluation') is None
for name in ('cluster', 'score', 'summarize', 'viewpoints', 'digest', 'repair_grounding'):
    assert importlib.util.find_spec('unspun.pipeline.' + name) is None, name
assert not any(name.startswith('unspun.evaluation') for name in sys.modules)
assert '/api/digest/latest' in app.openapi()['paths']
""",
        ],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(tmp_path), "UNSPUN_OPENROUTER_API_KEY": ""},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
