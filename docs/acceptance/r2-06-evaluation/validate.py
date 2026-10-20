"""Offline original/new freeze, import, contract and protected observer checks."""
import hashlib
import argparse
import json
import subprocess
import types
from datetime import UTC, datetime
from pathlib import Path
from unspun.core.member_contracts import member_contract
import unspun
import unspun.core.member_recall
import unspun.evaluation.member_quality
import unspun.pipeline.member_processing
ROOT=Path(__file__).resolve().parents[3]
OUT=Path(__file__).parent
BASE='c58a87881017a3b0b2e89de15bbf32279b9e6b39'
parser=argparse.ArgumentParser();parser.add_argument('--suffix',default='');suffix=parser.parse_args().suffix
assert not suffix or all(c in 'abcdefghijklmnopqrstuvwxyz0123456789-' for c in suffix)
def blob(name,rev=BASE):return subprocess.check_output(['git','show',rev+':'+name],cwd=ROOT)
def sha(data):return hashlib.sha256(data).hexdigest()
old=json.loads((ROOT/'docs/evaluations/r2/freeze-v1.json').read_text())
for row in old['files']:
    raw=blob(row['path'],old['base_revision']) if row['path']=='config/sources.yml' else (ROOT/row['path']).read_bytes()
    assert sha(raw)==row['sha256'],row['path']
prior=json.loads((ROOT/'docs/acceptance/r2-06/freeze-validation.json').read_text())
protected=[p for p in prior['protected_original_artifacts'] if p!='docs/evaluations/r2/README.md']
for name in protected:assert (ROOT/name).read_bytes()==blob(name),name
new=json.loads((ROOT/'docs/evaluations/r2/member-freeze-v1.json').read_text())
extra=json.loads((ROOT/'docs/evaluations/r2/member-availability-freeze-v1.json').read_text())
execution=json.loads((ROOT/'docs/evaluations/r2/member-execution-v1.json').read_text())
for row in [*new['files'],*extra['files'],*execution['files']]:assert sha((ROOT/row['path']).read_bytes())==row['sha256'],row['path']
assert (OUT/'member-recall-v1.py').read_bytes()==blob('server/src/unspun/core/member_recall.py')
module=types.ModuleType('retained_member_contract_v1')
exec(compile(blob('server/src/unspun/core/member_contracts.py'),'<v1-member-contract>','exec'),module.__dict__)
a,b=module.member_contract(),member_contract()
delta=[k for k in a if a[k]!=b[k]]
assert sorted(delta)==['recall','version']
modules=(unspun,unspun.core.member_recall,unspun.evaluation.member_quality,unspun.pipeline.member_processing)
imports={m.__name__:m.__file__ for m in modules}
assert all(str(ROOT) in value for value in imports.values())
for name in ('server/src/unspun/core/content_reading.py','server/src/unspun/pipeline/content_processing.py'):
    assert (ROOT/name).read_bytes()==blob(name)
source={str(p.relative_to(ROOT/'server/src/unspun')):sha(p.read_bytes()) for p in sorted((ROOT/'server/src/unspun').rglob('*.py'))}
(OUT/('import-check'+suffix+'.json')).write_text(json.dumps({'at':datetime.now(UTC).isoformat(),'worktree':str(ROOT),'actual_imports':imports,'source_sha256':source},indent=2)+'\n')
observer=Path('/Users/li.cong/.config/superpowers/worktrees/unspun/r2-source-increments')
head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=observer,text=True).strip()
status=subprocess.check_output(['git','status','--porcelain'],cwd=observer,text=True)
assert head.startswith('b5f812c') and not status
for p in list((observer/'server/src/unspun').rglob('*.py'))+list((observer/'config').glob('*.yml')):
    assert p.read_bytes()==subprocess.check_output(['git','show','HEAD:'+str(p.relative_to(observer))],cwd=observer)
(OUT/('protected-r204-worktree'+suffix+'.json')).write_text(json.dumps({'path':str(observer),'head':head,'status':status,'source_and_config_unchanged':True},indent=2)+'\n')
result={'at':datetime.now(UTC).isoformat(),'base_revision':BASE,'original_frozen_files_verified':len(old['files']),'new_frozen_files_verified':len({row['path'] for row in [*new['files'],*extra['files'],*execution['files']]}),'protected_original_files_verified':len(protected),'intentional_narrative_update':'docs/evaluations/r2/README.md appends this new batch; not an original frozen input','contract_delta_keys':delta,'r1_card_contract_and_processing_bytes_unchanged':True,'r204_worktree_protected':True,'new_user_ratings_written':0,'paid_calls':0}
(OUT/('freeze-validation'+suffix+'.json')).write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
