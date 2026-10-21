"""Append-only source/contract freeze and historical artifact validation before real output."""
import argparse,hashlib,importlib,json,subprocess
from datetime import UTC,datetime
from pathlib import Path
from sqlalchemy import create_engine,text
from sqlalchemy.orm import Session
from unspun.evaluation.member_quality import batch_state
ROOT=Path(__file__).resolve().parents[3];OUT=Path(__file__).parent
p=argparse.ArgumentParser();p.add_argument('--create',action='store_true');a=p.parse_args()
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
manifest=ROOT/'docs/evaluations/r2/member-repair-freeze-v1.json'
if a.create:
 assert not manifest.exists(),'source freeze is append-only'
 e=create_engine('postgresql+psycopg://unspun:unspun@localhost:5432/unspun_quality_r1_20261016')
 with Session(e) as s:
  s.execute(text('SET TRANSACTION READ ONLY'));state=batch_state(s)
 assert state['physical_requests']==59 and not state['unresolved_ids']
 paths=sorted((ROOT/'server/src/unspun').rglob('*.py'))+sorted((ROOT/'config').glob('*.yml'))
 paths += [ROOT/'docs/evaluations/r2/member-retest-v1.json',ROOT/'docs/evaluations/r2/member-blind-seal-v1.json',ROOT/'docs/evaluations/r2/member-blind-seal-v2.json']
 paths += sorted((ROOT/'server/tests').glob('test_member*.py'))
 value={'id':'r206-repair-source-freeze-v1','at':datetime.now(UTC).isoformat(),'previous_pool_requests':59,'previous_pool_known_usd':state['known_usd'],'new_real_requests_at_freeze':0,'root_blind_materials_read':False,'files':[{'path':str(p.relative_to(ROOT)),'sha256':sha(p)} for p in paths]}
 with manifest.open('x') as f:json.dump(value,f,indent=2)
value=json.loads(manifest.read_text())
for row in value['files']:assert sha(ROOT/row['path'])==row['sha256'],row['path']
old=json.loads((ROOT/'docs/evaluations/r2/freeze-v1.json').read_text())
for row in old['files']:
 data=subprocess.check_output(['git','show',old['base_revision']+':'+row['path']],cwd=ROOT) if row['path']=='config/sources.yml' else (ROOT/row['path']).read_bytes()
 assert hashlib.sha256(data).hexdigest()==row['sha256'],row['path']
seen=set()
for name in ['member-freeze-v1.json','member-execution-v1.json','member-availability-freeze-v1.json']:
 for row in json.loads((ROOT/'docs/evaluations/r2'/name).read_text())['files']:
  assert sha(ROOT/row['path'])==row['sha256'],row['path'];seen.add(row['path'])
tracked=subprocess.check_output(['git','ls-tree','-r','--name-only','7edad00','docs/evaluations/r2','docs/acceptance/r2-04','docs/acceptance/r2-06-evaluation'],cwd=ROOT,text=True).splitlines()
for name in tracked:
 assert (ROOT/name).read_bytes()==subprocess.check_output(['git','show','7edad00:'+name],cwd=ROOT),name
modules=['unspun','unspun.core.member_contracts','unspun.core.member_recall','unspun.pipeline.member_processing','unspun.evaluation.member_quality','unspun.evaluation.member_retest','unspun.evaluation.member_retest_challenge','unspun.core.billing','unspun.core.tasks']
imports={name:importlib.import_module(name).__file__ for name in modules}
assert all(str(ROOT/'server/src') in path for path in imports.values())
observer=Path('/Users/li.cong/.config/superpowers/worktrees/unspun/r2-source-increments')
assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=observer,text=True).startswith('b5f812c')
assert not subprocess.check_output(['git','status','--porcelain'],cwd=observer,text=True)
for name in ['server/src/unspun/core/billing.py','server/src/unspun/core/content_reading.py','server/src/unspun/pipeline/content_processing.py']:
 assert (ROOT/name).read_bytes()==subprocess.check_output(['git','show','7edad00:'+name],cwd=ROOT),name
report={'at':datetime.now(UTC).isoformat(),'source_freeze_sha256':sha(manifest),'frozen_source_config_registration_test_files':len(value['files']),'original_freeze_verified':len(old['files']),'old_member_freeze_verified':len(seen),'protected_prior_artifacts_unchanged':len(tracked),'original_prices_full_reservation_and_r1_contract_unchanged':True,'r204_worktree_unchanged':True,'actual_imports':imports,'blind_root_materials_read_during_repair':False,'new_paid_calls_at_freeze':0}
target=OUT/('freeze-created.json' if a.create else 'freeze-verified.json')
if not target.exists():
 with target.open('x') as f:json.dump(report,f,indent=2)
print(json.dumps({k:v for k,v in report.items() if k!='actual_imports'},indent=2))
