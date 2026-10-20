"""Read-only final material, admission, fingerprint and ledger proof before first paid output."""
import hashlib
import json
import subprocess
from datetime import UTC,datetime
from pathlib import Path
from sqlalchemy import select,text
from sqlalchemy.orm import Session
from unspun.core.billing import budget_status
from unspun.core.content_publication import qualified_item
from unspun.core.content_reading import ContentInput
from unspun.core.db import get_engine
from unspun.core.models import Article
from unspun.core.sources import load_sources
from unspun.evaluation.member_quality import registration,require_original_database,batch_state
from unspun.pipeline.content_processing import load_content,processing_fingerprint
ROOT=Path(__file__).resolve().parents[3];OUT=Path(__file__).parent
require_original_database();spec=registration();packages=json.loads((ROOT/'docs/evaluations/r2/member-inputs-v1.json').read_text())['packages']
with get_engine().connect() as c,c.begin():
 c.execute(text('SET TRANSACTION READ ONLY'));s=Session(bind=c);results=[]
 for p in packages:
  identity=p['article']['id']
  if any(i['article_id']==identity for i in spec['unavailable_inputs']):
   assert s.get(Article,identity) is None
   results.append({'article_id':identity,'status':'unavailable_identity_conflict','original_r1_qualification':p['observed_state']});continue
  content=load_content(s,identity);original=ContentInput.model_validate(p['original_input'])
  assert content.model_dump(mode='json')['paragraphs']==p['original_input']['paragraphs']
  assert processing_fingerprint(content,'card')==processing_fingerprint(original,'card')
  assert content.material_fingerprint==original.material_fingerprint
  item=qualified_item(s,identity,preview=False,as_of=datetime.now(UTC),sources=load_sources())
  results.append({'article_id':identity,'status':'qualified' if item else 'original_admission_exclusion','material_id':content.material_id,'original_material_id':original.material_id,'material_fingerprint':content.material_fingerprint,'card_processing_fingerprint':processing_fingerprint(content,'card'),'paragraphs_unchanged':True})
 state=batch_state(s);assert state['physical_requests']==0
 assert sum(r['status']=='qualified' for r in results)==21
 assert sum(r['status']=='original_admission_exclusion' for r in results)==10
 assert sum(r['status']=='unavailable_identity_conflict' for r in results)==1
 data={'at':datetime.now(UTC).isoformat(),'source_revision':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'schema':s.scalar(text('SELECT version_num FROM alembic_version')),'materials':results,'registered_queries':len(spec['queries']),'executable_queries':len(spec['queries'])-len(spec['unavailable_inputs']),'budget':budget_status(s),'batch':state,'paid_requests':0,'database_writes':0,'all_original_processing_fingerprints_and_paragraphs_preserved':True,'scope':'Only appendable frozen real versions; no replacement with older object 19 and no R1 regeneration.'}
with (OUT/'prepaid-proof.json').open('x') as f:json.dump(data,f,ensure_ascii=False,indent=2,default=str)
print('Final proof: 21 qualified, 10 admission exclusions, 1 unavailable; 0 new calls')
