"""Read-only narrow before/after execution windows; no paid requests or DB mutations."""
import argparse,json,os,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];OUT=Path(__file__).parent
p=argparse.ArgumentParser();p.add_argument('phase',choices=['prepay','final']);args=p.parse_args()
jobs=[('production',['ssh','unspun','docker exec -i unspun-r1-worker-1 python - production'],'docs/acceptance/r2-04/snapshot.py',None),('member-chain',['ssh','unspun','docker exec -i unspun-r1-worker-1 python -'],'docs/acceptance/r2-06/member-chain-probe.py',None)]
if args.phase=='final':jobs.append(('evaluation',[str(ROOT/'server/.venv/bin/python'),'-','evaluation'],'docs/acceptance/r2-04/snapshot.py',dict(os.environ,UNSPUN_DATABASE_URL='postgresql+psycopg://unspun:unspun@localhost:5432/unspun_quality_r1_20261016')))
for name,command,path,env in jobs:
 value=json.loads(subprocess.check_output(command,input=(ROOT/path).read_text(),text=True,timeout=60,env=env))
 with (OUT/(args.phase+'-'+name+'.json')).open('x') as f:json.dump(value,f,indent=2,ensure_ascii=False)
 print(name,flush=True)
