"""Full original-ledger backup/restoration and original-row preservation; no paid entry."""
import argparse,hashlib,json,subprocess
from datetime import UTC,datetime
from pathlib import Path
from sqlalchemy import create_engine,inspect,text
OUT=Path(__file__).parent;ORIGINAL='unspun_quality_r1_20261016'
PRIVATE=Path.home()/'.cache/unspun-r206-zero-paid-20261021'
PRIVATE.mkdir(mode=0o700,exist_ok=True);PRIVATE.chmod(0o700)
def engine(db):
 assert db==ORIGINAL or db.startswith('unspun_r206_zero_paid_')
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
backup=PRIVATE/f'{a.phase}-r206-zero-paid.dump'
restore='unspun_r206_zero_paid_restore_'+a.phase+'_20261021'
before=snapshot(ORIGINAL)
with backup.open('xb') as f:subprocess.run(['docker','exec','unspun-db-1','pg_dump','-U','unspun','-d',ORIGINAL,'-Fc'],stdout=f,check=True,timeout=60)
subprocess.run(['docker','exec','unspun-db-1','createdb','-U','unspun',restore],check=True,timeout=30)
with backup.open('rb') as f:subprocess.run(['docker','exec','-i','unspun-db-1','pg_restore','-U','unspun','-d',restore,'--no-owner','--exit-on-error'],stdin=f,check=True,timeout=60)
assert before==snapshot(restore)==snapshot(ORIGINAL)
report={'at':datetime.now(UTC).isoformat(),'source':ORIGINAL,'restore':restore,'snapshot':before,'all_table_counts_hashes_sequences_match':True,'backup':{'path':str(backup),'sha256':hashlib.sha256(backup.read_bytes()).hexdigest(),'bytes':backup.stat().st_size},'paid_requests':0,'parallel_spending_allocation_created':False}
with (OUT/(a.phase+'-recovery.json')).open('x') as f:json.dump(report,f,indent=2,default=str)
print('Full backup/restore verified:',restore)
