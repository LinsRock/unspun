"""Retain official calls and verify full recovery plus old-row preservation, without paid HTTP."""
import hashlib
import json
import subprocess
from datetime import UTC,datetime
from pathlib import Path
from sqlalchemy import create_engine,inspect,text
ORIGINAL='unspun_quality_r1_20261016'
OLD_RESTORE='unspun_r206_eval_restore_20261020'
RESTORED='unspun_r206_eval_post_restore_20261020'
OUT=Path(__file__).parent
BACKUP=Path.home()/'.cache/unspun-r206-eval-20261020/official-evaluation-after-r206-v1.dump'
def engine(database):
 assert database in (ORIGINAL,OLD_RESTORE,RESTORED)
 return create_engine('postgresql+psycopg://unspun:unspun@localhost:5432/'+database)
def snapshot(database):
 e=engine(database)
 with e.connect() as c,c.begin():
  c.execute(text('SET TRANSACTION READ ONLY'));tables={}
  for name in sorted(inspect(c).get_table_names()):
   q=c.dialect.identifier_preparer.quote(name)
   tables[name]=dict(c.execute(text(f"SELECT count(*) AS rows,md5(string_agg(to_jsonb(t)::text,'' ORDER BY to_jsonb(t)::text)) AS hash FROM {q} t")).mappings().one())
  seq=[dict(r) for r in c.execute(text("SELECT sequencename,last_value FROM pg_sequences WHERE schemaname='public' ORDER BY sequencename")).mappings()]
 e.dispose();return {'tables':tables,'sequences':seq}
source=snapshot(ORIGINAL)
with BACKUP.open('xb') as f:subprocess.run(['docker','exec','unspun-db-1','pg_dump','-U','unspun','-d',ORIGINAL,'-Fc'],stdout=f,check=True,timeout=60)
subprocess.run(['docker','exec','unspun-db-1','createdb','-U','unspun',RESTORED],check=True)
with BACKUP.open('rb') as f:subprocess.run(['docker','exec','-i','unspun-db-1','pg_restore','-U','unspun','-d',RESTORED,'--no-owner','--exit-on-error'],stdin=f,check=True,timeout=60)
restored=snapshot(RESTORED)
assert source==restored==snapshot(ORIGINAL)
old_e,new_e=engine(OLD_RESTORE),engine(ORIGINAL)
retained=[];policy=None
with old_e.connect() as old,old.begin(),new_e.connect() as new,new.begin():
 old.execute(text('SET TRANSACTION READ ONLY'));new.execute(text('SET TRANSACTION READ ONLY'))
 for name in sorted(inspect(old).get_table_names()):
  q=old.dialect.identifier_preparer.quote(name)
  keys=inspect(old).get_pk_constraint(name)['constrained_columns']
  before=[dict(r) for r in old.execute(text('SELECT * FROM '+q)).mappings()]
  after=[dict(r) for r in new.execute(text('SELECT * FROM '+q)).mappings()]
  if not before:
   retained.append({'table':name,'old_rows':0,'preserved':True});continue
  assert keys,name
  current={tuple(r[k] for k in keys):r for r in after}
  for row in before:
   actual=current[tuple(row[k] for k in keys)]
   if name=='budget_policy':
    expected=dict(row);expected['stage_caps']={'topic_embedding':'0.02','topic_judgment':'0.08','topic_review':'0.20'}
    assert actual==expected
    policy={'only_stage_caps_changed':True,'before':row['stage_caps'],'after':actual['stage_caps']}
   else:assert actual==row,(name,tuple(row[k] for k in keys))
  retained.append({'table':name,'old_rows':len(before),'preserved':True})
 unknown=[dict(r) for r in new.execute(text("SELECT id,status,reserved_usd::text AS reserved_usd FROM billed_requests WHERE status IN ('reserved','usage_unknown') ORDER BY id")).mappings()]
report={'at':datetime.now(UTC).isoformat(),'source':ORIGINAL,'restored':RESTORED,'backup':{'path':str(BACKUP),'bytes':BACKUP.stat().st_size,'sha256':hashlib.sha256(BACKUP.read_bytes()).hexdigest()},'source_snapshot':source,'restored_snapshot':restored,'all_rows_counts_hashes_sequences_match':True,'original_old_rows':retained,'original_policy':policy,'unresolved_requests':unknown,'original_unknown_holds_released':False,'paid_requests':0,'parallel_spend_allocation_created':False,'resources_retained':True}
with (OUT/'official-restore.json').open('x') as f:json.dump(report,f,default=str,indent=2)
print('Official full recovery and original-row retention verified')
