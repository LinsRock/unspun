"""Append-only v4 source freeze, previous immutable evidence and original-ledger audit."""
import argparse,hashlib,importlib,json,subprocess
from datetime import UTC,datetime
from decimal import Decimal
from pathlib import Path
from sqlalchemy import text
from sqlalchemy.orm import Session
from unspun.core.db import get_engine
from unspun.core.member_contracts import member_contract
from unspun.evaluation.member_quality import batch_state
ROOT=Path(__file__).resolve().parents[3];OUT=Path(__file__).parent;REG=ROOT/'docs/evaluations/r2'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def gitdata(revision,path):return subprocess.check_output(['git','show',revision+':'+path],cwd=ROOT)
p=argparse.ArgumentParser();p.add_argument('--create',action='store_true');a=p.parse_args();manifest=REG/'member-grounding-freeze-v1.json'
execution=json.loads((REG/'member-grounding-budget-v1.json').read_text());assert execution['contract']==member_contract()
if a.create:
 assert not manifest.exists()
 with Session(get_engine()) as s:
  s.execute(text('SET TRANSACTION READ ONLY'));state=batch_state(s)
  assert state['physical_requests']==107 and abs(Decimal(state['known_usd'])-Decimal('0.03171912'))<Decimal('0.0000000001') and not state['unresolved_ids']
  holds=[dict(r) for r in s.execute(text("SELECT id,status,reserved_usd::text,provider_generation_id FROM billed_requests WHERE status IN ('reserved','usage_unknown') ORDER BY id")).mappings()]
  assert holds==execution['original_holds']
 paths=sorted((ROOT/'server/src/unspun').rglob('*.py'))+sorted((ROOT/'config').glob('*.yml'))+sorted((ROOT/'server/tests').glob('test_member*.py'))
 paths += [REG/n for n in ['member-grounding-budget-v1.json','member-grounding-exposed-v1.json','member-grounding-challenges-v1.json','member-grounding-exposed-inputs-v1.json.gz']]
 value={'id':'r206-grounding-source-freeze-v1','at':datetime.now(UTC).isoformat(),'base_revision':'4f275b9d236acc315c49a735c6527b43ffc7cde9','previous_physical_requests':107,'previous_known_usd':'0.03171912','new_paid_requests_at_freeze':0,'new_blind_prepared':False,'exposed_queries_are_not_blind':True,'files':[{'path':str(p.relative_to(ROOT)),'sha256':sha(p)} for p in paths]}
 with manifest.open('x') as f:json.dump(value,f,indent=2)
value=json.loads(manifest.read_text())
for row in value['files']:assert sha(ROOT/row['path'])==row['sha256'],row['path']
prior=json.loads((REG/'member-repair-freeze-v1.json').read_text())
for row in prior['files']:assert hashlib.sha256(gitdata('4f275b9',row['path'])).hexdigest()==row['sha256'],row['path']
old=json.loads((REG/'freeze-v1.json').read_text())
for row in old['files']:
 data=gitdata(old['base_revision'],row['path']) if row['path']=='config/sources.yml' else (ROOT/row['path']).read_bytes()
 assert hashlib.sha256(data).hexdigest()==row['sha256'],row['path']
tracked=subprocess.check_output(['git','ls-tree','-r','--name-only','4f275b9','docs/evaluations/r2','docs/acceptance/r2-04','docs/acceptance/r2-06-evaluation','docs/acceptance/r2-06-repair','docs/acceptance/r2-06-repair-2026-10-21.md'],cwd=ROOT,text=True).splitlines()
for name in tracked:assert (ROOT/name).read_bytes()==gitdata('4f275b9',name),name
for name in ['server/src/unspun/core/billing.py','server/src/unspun/core/content_reading.py','server/src/unspun/pipeline/content_processing.py','server/pyproject.toml','server/uv.lock']:
 assert (ROOT/name).read_bytes()==gitdata('4f275b9',name),name
protected=Path('/Users/li.cong/.config/superpowers/worktrees/unspun/r2-source-increments')
assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=protected,text=True).startswith('b5f812c')
assert not subprocess.check_output(['git','status','--porcelain'],cwd=protected,text=True)
imports={n:importlib.import_module(n).__file__ for n in ['unspun.core.member_contracts','unspun.core.member_evidence','unspun.pipeline.member_processing','unspun.evaluation.member_grounding','unspun.evaluation.member_grounding_challenge']}
assert all(str(ROOT/'server/src') in p for p in imports.values())
report={'at':datetime.now(UTC).isoformat(),'source_freeze_sha256':sha(manifest),'frozen_files':len(value['files']),'previous_v3_source_frozen_blobs_verified':len(prior['files']),'original_r2_freeze_verified':len(old['files']),'previous_evidence_files_unchanged':len(tracked),'billing_full_window_prices_R1_dependencies_unchanged':True,'r204_original_worktree_unchanged':True,'actual_imports':imports,'new_paid_requests_at_freeze':0,'new_blind_prepared':False}
name='freeze-created.json' if a.create else 'freeze-verified.json'
if not (OUT/name).exists():
 with (OUT/name).open('x') as f:json.dump(report,f,indent=2)
print(json.dumps({k:v for k,v in report.items() if k!='actual_imports'},indent=2))
