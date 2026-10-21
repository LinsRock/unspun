"""Read-only production fee window for separating original R1 calls from the retest."""
import json,subprocess
from pathlib import Path
OUT=Path(__file__).parent;ROOT=OUT.parents[2]
start=json.load(open(OUT/'prepay-production.json'))['started_at']
script=(ROOT/'docs/acceptance/r2-06-evaluation/production-cost-window.py').read_text().replace("START='2026-10-20T11:35:16.244985+00:00'",'START='+repr(start))
r=subprocess.run(['ssh','unspun','docker exec -i unspun-api-1 python -'],input=script,text=True,capture_output=True,check=True,timeout=60)
with (OUT/'production-fee-window.json').open('x') as f:json.dump(json.loads(r.stdout),f,indent=2,ensure_ascii=False)
print('Natural R1 physical requests and fees captured separately')
