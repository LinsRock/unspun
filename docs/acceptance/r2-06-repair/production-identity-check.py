"""Prove retained identity rows are unchanged while natural R1 observations append."""
import json
import subprocess
from pathlib import Path
OUT=Path(__file__).parent
before=json.loads((OUT/'predeploy-retained.json').read_text())['tables']
spec={k:before[k] for k in ('content_identities','content_urls')}
script='BASELINE = '+repr(spec)+'\n'+'''
import json
from datetime import UTC,datetime
from sqlalchemy import text
from unspun.core.db import get_engine
out={'at':datetime.now(UTC).isoformat(),'read_only':True,'tables':{}}
with get_engine().connect() as c,c.begin():
 c.execute(text('SET TRANSACTION READ ONLY'))
 for table,prior in BASELINE.items():
  n=int(prior['rows'])
  rows=dict(c.execute(text("SELECT count(*) AS rows,md5(string_agg(to_jsonb(t)::text,'' ORDER BY to_jsonb(t)::text)) AS hash FROM (SELECT * FROM "+table+" ORDER BY id LIMIT :n) t"),{'n':n}).mappings().one())
  additions=[dict(r) for r in c.execute(text('SELECT x.id,x.article_id,a.source_id,a.processing_track FROM '+table+' x JOIN articles a ON a.id=x.article_id WHERE x.id NOT IN (SELECT id FROM '+table+' ORDER BY id LIMIT :n) ORDER BY x.id'),{'n':n}).mappings()]
  out['tables'][table]={'original_rows':prior,'current_original_prefix':rows,'original_prefix_matches':rows==prior,'natural_additions':additions}
print(json.dumps(out,indent=2))
'''
r=subprocess.run(['ssh','unspun','docker exec -i unspun-api-1 python -'],input=script,text=True,capture_output=True,check=True,timeout=60)
data=json.loads(r.stdout)
assert all(t['original_prefix_matches'] for t in data['tables'].values())
with (OUT/'production-identity-check.json').open('x') as f:json.dump(data,f,indent=2)
print('All original identity/URL rows preserved; natural additions recorded')
