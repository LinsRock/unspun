"""Read-only receipt and key lookup after the first unknown; never retry paid work."""
import json
from datetime import UTC,datetime
from pathlib import Path
import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session
from unspun.core.billing import budget_status
from unspun.core.billing_admin import provider_key_status
from unspun.core.config import get_settings
from unspun.core.db import get_engine
from unspun.evaluation.member_quality import batch_state,require_original_database
from unspun.evaluation.run_quality import load_key_from_ssh
require_original_database();OUT=Path(__file__).parent
load_key_from_ssh('unspun');key=get_settings().openrouter_api_key
with Session(get_engine()) as s:
 s.execute(text('SET TRANSACTION READ ONLY'))
 rows=[dict(r) for r in s.execute(text("SELECT id,status,reserved_usd::text,provider_generation_id,http_status,task_id,article_id,response_payload FROM billed_requests WHERE status IN ('reserved','usage_unknown') ORDER BY id")).mappings()]
 new=next(r for r in rows if r['id']=='9bc36dfe3a5c455e9df54756b70f1579')
 result={'at':datetime.now(UTC).isoformat(),'batch':batch_state(s),'budget':budget_status(s),'all_holds':rows,'paid_requests':0,'database_mutations':0,'all_paid_phases_stopped':True}
with httpx.Client(base_url=get_settings().openrouter_base_url,headers={'Authorization':'Bearer '+key},proxy='socks5://127.0.0.1:12061',timeout=30) as client:
 receipt=client.get('/generation',params={'id':new['provider_generation_id']});result['generation_lookup']={'http_status':receipt.status_code,'payload':receipt.json()};result['provider']=provider_key_status(client)
with (OUT/'unknown-cost-check.json').open('x') as f:json.dump(result,f,indent=2,ensure_ascii=False,default=str)
print(json.dumps({'generation_lookup':result['generation_lookup'],'known_usd':result['batch']['known_usd'],'held_usd':result['batch']['held_usd'],'unknown_holds':len(rows),'provider_usage':result['provider']['usage'],'database_mutations':0},indent=2))
