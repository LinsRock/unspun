"""Offline freeze/source/evidence integrity checks for the first R2-06 batch."""
import hashlib
import importlib.util
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).parent
BASE = "ed86474c904ac136e3d933c7c736f18de3d7902b"
freeze = json.loads((ROOT / "docs/evaluations/r2/freeze-v1.json").read_text())
checks = []
for value in freeze['files']:
    raw = subprocess.check_output(['git','show',freeze['base_revision']+':'+value['path']],cwd=ROOT) if value['path']=='config/sources.yml' else (ROOT/value['path']).read_bytes()
    assert hashlib.sha256(raw).hexdigest()==value['sha256'],value['path']
    checks.append(value['path'])
prior=json.loads((ROOT/'docs/acceptance/r2-05/freeze-validation.json').read_text())
protected=[]
for name in prior['config_and_r204_and_r2_original_artifacts_byte_unchanged']:
    raw=subprocess.check_output(['git','show',BASE+':'+name],cwd=ROOT)
    assert (ROOT/name).read_bytes()==raw,name
    protected.append(name)
local=ROOT/'server/src/unspun'
imports={str(p.relative_to(local)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(local.rglob('*.py'))}
import unspun,unspun.core.member_models,unspun.pipeline.member_processing
actual={m.__name__:m.__file__ for m in (unspun,unspun.core.member_models,unspun.pipeline.member_processing)}
assert all(str(ROOT) in v for v in actual.values())
(OUT/'import-check.json').write_text(json.dumps({'worktree':str(ROOT),'actual_imports':actual,'source_sha256':imports},indent=2)+'\n')
observer=Path('/Users/li.cong/.config/superpowers/worktrees/unspun/r2-source-increments')
head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=observer,text=True).strip()
status=subprocess.check_output(['git','status','--porcelain'],cwd=observer,text=True)
assert head.startswith('b5f812c') and status==''
for p in list((observer/'server/src/unspun').rglob('*.py'))+list((observer/'config').glob('*.yml')):
    name=str(p.relative_to(observer))
    assert p.read_bytes()==subprocess.check_output(['git','show','HEAD:'+name],cwd=observer)
(OUT/'protected-r204-worktree.json').write_text(json.dumps({'path':str(observer),'head':head,'status':status,'source_and_config_unchanged':True},indent=2)+'\n')
(OUT/'freeze-validation.json').write_text(json.dumps({'base_revision':BASE,'registered_frozen_files_verified':len(checks),'protected_original_artifacts':protected,'new_ratings_written':0},indent=2)+'\n')
print(json.dumps({'frozen':len(checks),'protected':len(protected),'current_sources':len(imports),'r204_worktree_protected':True}))
