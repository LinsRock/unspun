"""Read-only narrow before/after paid-run ledger and final disabled-chain snapshots."""
import argparse,json,os,subprocess
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('phase',choices=['prepay','final']);a=p.parse_args()
ROOT=Path(__file__).resolve().parents[3];OUT=Path(__file__).parent
jobs=[('production','docs/acceptance/r2-04/snapshot.py',['ssh','unspun','docker exec -i unspun-r1-worker-1 python - production'],None)]
if a.phase=='final':
 jobs += [('member-chain','docs/acceptance/r2-06/member-chain-probe.py',['ssh','unspun','docker exec -i unspun-r1-worker-1 python -'],None),('evaluation','docs/acceptance/r2-04/snapshot.py',[str(ROOT/'server/.venv/bin/python'),'-','evaluation'],dict(os.environ,UNSPUN_DATABASE_URL='postgresql+psycopg://unspun:unspun@localhost:5432/unspun_quality_r1_20261016'))]
for name,path,command,env in jobs:
 target=OUT/(a.phase+'-'+name+'.json');assert not target.exists()
 r=subprocess.run(command,input=(ROOT/path).read_text(),text=True,capture_output=True,check=True,timeout=60,env=env)
 with target.open('x') as f:json.dump(json.loads(r.stdout),f,indent=2,ensure_ascii=False)
 print(target.name,flush=True)
