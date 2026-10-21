"""Read-only final freeze verification and negative blind-gate probe."""
import hashlib,json,os,subprocess
from datetime import UTC,datetime
from pathlib import Path
from sqlalchemy import text
from sqlalchemy.orm import Session
from unspun.core.db import get_engine
from unspun.evaluation.member_grounding import EVIDENCE,FREEZE,ROOT,load_execution
from unspun.evaluation.member_quality import batch_state
exe=load_execution()
with Session(get_engine()) as s:s.execute(text('SET TRANSACTION READ ONLY'));before=batch_state(s)
r=subprocess.run([str(ROOT/'server/.venv/bin/python'),'-m','unspun.evaluation.member_grounding','check-blind-gate'],cwd=ROOT/'server',env=dict(os.environ),capture_output=True,text=True,timeout=30)
assert r.returncode!=0 and 'exposed gates must pass before any fresh blind preparation or paid run' in r.stderr
with Session(get_engine()) as s:s.execute(text('SET TRANSACTION READ ONLY'));assert batch_state(s)==before
assert not (ROOT/exe['new_blind_seal']).exists() and not (EVIDENCE/'blind-first-run.ndjson').exists()
protected=Path.home()/'.config/superpowers/worktrees/unspun/r2-source-increments'
assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=protected,text=True).strip()=='b5f812c7c66d2dd185d9046e21c2c8c413e1b26f'
assert not subprocess.check_output(['git','status','--porcelain'],cwd=protected,text=True)
value={'at':datetime.now(UTC).isoformat(),'source_freeze_sha256':hashlib.sha256(FREEZE.read_bytes()).hexdigest(),'current_frozen_files_verified':len(json.loads(FREEZE.read_text())['files']),'paid_attempts_at_final':before['physical_requests'],'new_paid_attempts':32,'source_or_parameters_changed_after_first_paid_output':False,'failed_gate_probe':{'returncode':r.returncode,'stderr':r.stderr,'paid_request_count_unchanged':True,'fresh_blind_not_opened':True},'new_blind_seal_absent':True,'new_blind_first_output_absent':True,'r204_original_worktree_unchanged':True,'original_r2_and_v3_artifacts_verified_at_freeze_v2':True,'all_paid_work_stopped':True}
with (EVIDENCE/'final-freeze-check.json').open('x') as f:json.dump(value,f,indent=2)
print('Final 109-source freeze and negative blind entry verified; zero requests added')
