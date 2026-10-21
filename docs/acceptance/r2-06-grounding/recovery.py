"""Full original-ledger backup/restoration and original-row preservation; no paid entry."""
import argparse,hashlib,json,subprocess
from datetime import UTC,datetime
from pathlib import Path
from sqlalchemy import create_engine,inspect,text
OUT=Path(__file__).parent;ORIGINAL='unspun_quality_r1_20261016'
PRIVATE=Path.home()/'.cache/unspun-r206-grounding-20261021'
PRIVATE.mkdir(mode=0o700,exist_ok=True);PRIVATE.chmod(0o700)
def engine(db):
 assert db==ORIGINAL or db.startswith('unspun_r206_grounding_')
 return create_engine('postgresql+psycopg://unspun:unspun@localhost:5432/'+db)
def snapshot(db):
 e=engine(db)
 with e.connect() as c,c.begin():
  c.execute(text('SET TRANSACTION READ ONLY'));tables={}
  for name in sorted(inspect(c).get_table_names()):
   q=c.dialect.identifier_preparer.quote(name)
   tables[name]=dict(c.execute(text(f"SELECT count(*) AS rows,md5(string_agg(to_jsonb(t)::text,'' ORDER BY to_jsonb(t)::text)) AS hash FROM {q} t")).mappings().one())
  seq=[dict(r) for r in c.execute(text("SELECT sequencename,last_value FROM pg_sequences WHERE schemaname='public' ORDER BY sequencename")).mappings()]
 e.dispose();return {'tables':tables,'sequences':seq}
p=argparse.ArgumentParser();p.add_argument('phase',choices=['before','after']);a=p.parse_args()
backup=PRIVATE/f'{a.phase}-r206-grounding.dump'
restore='unspun_r206_grounding_restore_'+a.phase+'_20261021'
before=snapshot(ORIGINAL)
with backup.open('xb') as f:subprocess.run(['docker','exec','unspun-db-1','pg_dump','-U','unspun','-d',ORIGINAL,'-Fc'],stdout=f,check=True,timeout=60)
subprocess.run(['docker','exec','unspun-db-1','createdb','-U','unspun',restore],check=True,timeout=30)
with backup.open('rb') as f:subprocess.run(['docker','exec','-i','unspun-db-1','pg_restore','-U','unspun','-d',restore,'--no-owner','--exit-on-error'],stdin=f,check=True,timeout=60)
assert before==snapshot(restore)==snapshot(ORIGINAL)
report={'at':datetime.now(UTC).isoformat(),'source':ORIGINAL,'restore':restore,'snapshot':before,'all_table_counts_hashes_sequences_match':True,'backup':{'path':str(backup),'sha256':hashlib.sha256(backup.read_bytes()).hexdigest(),'bytes':backup.stat().st_size},'paid_requests':0,'parallel_spending_allocation_created':False}
if a.phase=='after':
 olde,newe=engine('unspun_r206_grounding_restore_before_20261021'),engine(ORIGINAL)
 retained=[]
 with olde.connect() as old,old.begin(),newe.connect() as new,new.begin():
  old.execute(text('SET TRANSACTION READ ONLY'));new.execute(text('SET TRANSACTION READ ONLY'))
  for name in sorted(inspect(old).get_table_names()):
   q=old.dialect.identifier_preparer.quote(name);keys=inspect(old).get_pk_constraint(name)['constrained_columns']
   rows=[dict(r) for r in old.execute(text('SELECT * FROM '+q)).mappings()]
   current={tuple(r[k] for k in keys):dict(r) for r in new.execute(text('SELECT * FROM '+q)).mappings()}
   unchanged=all(current[tuple(r[k] for k in keys)]==r for r in rows)
   allowed=False
   if name=='budget_policy' and not unchanged:
    revision=json.loads((OUT/'allocation.json').read_text())
    assert len(rows)==1 and revision['before']['stage_caps']==rows[0]['stage_caps']
    expected={**rows[0],'stage_caps':revision['after']['stage_caps']}
    assert current[tuple(rows[0][k] for k in keys)]==expected
    allowed=True
   else:assert unchanged,name
   retained.append({'table':name,'original_rows':len(rows),'all_original_rows_unchanged':unchanged,'authorized_registered_stage_caps_only':allowed})
 report['retained_original_rows']=retained
with (OUT/(a.phase+'-recovery.json')).open('x') as f:json.dump(report,f,indent=2,default=str)
print('Full backup/restore verified:',restore)
