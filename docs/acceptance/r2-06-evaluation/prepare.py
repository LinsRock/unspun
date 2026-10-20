"""Back up the original cumulative ledger and verify isolated restoration before upgrade.

Default rehearses only. --apply-original requires the retained successful rehearsal
and an unchanged original snapshot; use only after the preparation PR is reviewed.
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from sqlalchemy import create_engine, inspect, text
ROOT=Path(__file__).resolve().parents[3]
OUT=Path(__file__).parent
ORIGINAL='unspun_quality_r1_20261016'
RESTORED='unspun_r206_eval_restore_20261020'
PRIVATE=Path.home()/'.cache/unspun-r206-eval-20261020'
PRIVATE.mkdir(mode=0o700,parents=True,exist_ok=True)
BACKUP=PRIVATE/'original-evaluation-000015.dump'

def url(database):
    assert database in (ORIGINAL,RESTORED)
    return 'postgresql+psycopg://unspun:unspun@localhost:5432/'+database

def snapshot(database):
    engine=create_engine(url(database))
    with engine.connect() as conn,conn.begin():
        conn.execute(text('SET TRANSACTION READ ONLY'))
        tables={}
        for table in sorted(inspect(conn).get_table_names()):
            quoted=conn.dialect.identifier_preparer.quote(table)
            tables[table]=dict(conn.execute(text(f"SELECT count(*) AS rows,md5(string_agg(to_jsonb(t)::text,'' ORDER BY to_jsonb(t)::text)) AS hash FROM {quoted} t")).mappings().one())
        sequences=[dict(r) for r in conn.execute(text("SELECT sequencename,last_value FROM pg_sequences WHERE schemaname='public' ORDER BY sequencename")).mappings()]
    engine.dispose()
    return {'tables':tables,'sequences':sequences}

def migrate(database):
    result=subprocess.run([sys.executable,'-m','alembic','upgrade','head'],cwd=ROOT/'server',env=dict(os.environ,PYTHONPATH=str(ROOT/'server/src'),UNSPUN_DATABASE_URL=url(database)),capture_output=True,text=True,timeout=60)
    assert result.returncode==0, result.stderr
    return {'exit_code':result.returncode,'stdout':result.stdout,'stderr':result.stderr}

def old_equal(before,after):
    return all(after['tables'][k]==v for k,v in before['tables'].items() if k!='alembic_version') and all(row in after['sequences'] for row in before['sequences'])

p=argparse.ArgumentParser(description=__doc__);p.add_argument('--apply-original',action='store_true');args=p.parse_args()
if args.apply_original:
    rehearsal=json.loads((OUT/'evaluation-restore.json').read_text())
    assert rehearsal['all_original_rows_restored'] and rehearsal['old_rows_preserved_after_upgrade']
    assert hashlib.sha256(BACKUP.read_bytes()).hexdigest()==rehearsal['backup']['sha256']
    assert snapshot(ORIGINAL)==rehearsal['before'], 'the original ledger changed since rehearsal'
    report={'at':datetime.now(UTC).isoformat(),'original':ORIGINAL,'before':snapshot(ORIGINAL),'upgrade':migrate(ORIGINAL)}
    report['after']=snapshot(ORIGINAL)
    report['old_rows_and_sequences_preserved']=old_equal(report['before'],report['after'])
    assert report['old_rows_and_sequences_preserved']
    with (OUT/'original-upgrade.json').open('x') as f:json.dump(report,f,indent=2,default=str)
else:
    before=snapshot(ORIGINAL)
    with BACKUP.open('xb') as f:
        subprocess.run(['docker','exec','unspun-db-1','pg_dump','-U','unspun','-d',ORIGINAL,'-Fc'],stdout=f,check=True,timeout=60)
    subprocess.run(['docker','exec','unspun-db-1','createdb','-U','unspun',RESTORED],check=True)
    with BACKUP.open('rb') as f:
        subprocess.run(['docker','exec','-i','unspun-db-1','pg_restore','-U','unspun','-d',RESTORED,'--no-owner','--exit-on-error'],stdin=f,check=True,timeout=60)
    restored=snapshot(RESTORED)
    assert before==restored
    upgrade=migrate(RESTORED);after=snapshot(RESTORED)
    assert old_equal(before,after)
    repeat=migrate(RESTORED);assert snapshot(RESTORED)==after
    assert snapshot(ORIGINAL)==before
    report={'at':datetime.now(UTC).isoformat(),'original':ORIGINAL,'restored':RESTORED,'before':before,'restored_before_upgrade':restored,'after_upgrade':after,'upgrade':upgrade,'repeat_upgrade':repeat,'all_original_rows_restored':True,'old_rows_preserved_after_upgrade':True,'original_database_writes':0,'paid_requests':0,'parallel_allocation_created':False,'backup':{'path':str(BACKUP),'bytes':BACKUP.stat().st_size,'sha256':hashlib.sha256(BACKUP.read_bytes()).hexdigest()}}
    with (OUT/'evaluation-restore.json').open('x') as f:json.dump(report,f,indent=2,default=str)
print(json.dumps({k:v for k,v in report.items() if isinstance(v,(bool,str,int))},indent=2))
