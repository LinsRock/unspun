"""Read-only retained production fee window; no new-chain requests or mutations."""
import json,subprocess
from pathlib import Path
OUT=Path(__file__).parent;ROOT=OUT.parents[2]
start=json.loads((OUT/'prepay-production.json').read_text())['started_at']
script=(ROOT/'docs/acceptance/r2-06-evaluation/production-cost-window.py').read_text().replace("START='2026-10-20T11:35:16.244985+00:00'",'START='+repr(start))
value=json.loads(subprocess.check_output(['ssh','unspun','docker exec -i unspun-api-1 python -'],input=script,text=True,timeout=60))
with (OUT/'production-fee-window.json').open('x') as f:json.dump(value,f,indent=2,ensure_ascii=False)
print('Concurrent R1 production fee window captured independently')
