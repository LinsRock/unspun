import json,httpx
from datetime import UTC,datetime
from unspun.core.config import get_settings
ids=['gen-1792228899-g8CyAm1fHk5FLCwMg6dG', 'gen-1792504851-aJfa3TLvI95u9KPleuZ5', 'gen-1792512014-KqEUkGHgrUKye3TKAmj1', 'gen-1792512018-71NfbpIwAaqeDbv8ziXL', 'gen-1792519207-8n4WIU9qeFgZVkQTkERc', 'gen-1792519216-6XQG14GjkGpNZq76sY7K', 'gen-1792562417-BlLff7A3yNgxPx26H6vV', 'gen-1792562421-q2hFvof5pkEhaVVhharA', 'gen-1792567035-xqUccUdgq5n1RaXx5duo', 'gen-1792569612-QscEJVHs6x8wizbe0mOA', 'gen-1792569613-NIoWKFZQpIbeAzom1R6B', 'gen-1792569619-QQOjDARd72XBKzrv7sT5']
s=get_settings(); assert s.openrouter_api_key, "provider credential unavailable before HTTP"
out={"started_at":datetime.now(UTC).isoformat(),"maximum_generation_gets":32,"retry_count":0,"generation":[],"paid_requests":0,"database_writes":0}
with httpx.Client(base_url=s.openrouter_base_url,headers={"Authorization":"Bearer "+s.openrouter_api_key},timeout=15) as c:
 for identity in ids:
  row={"id":identity,"at":datetime.now(UTC).isoformat(),"method":"GET"}
  try:
   r=c.get('/generation',params={"id":identity});row.update(http_status=r.status_code,payload=r.json())
  except Exception as e:row.update(error=type(e).__name__)
  out['generation'].append(row)
 try:
  r=c.get('/key');out['key']={"http_status":r.status_code,"payload":r.json()}
 except Exception as e:out['key']={"error":type(e).__name__}
out['completed_at']=datetime.now(UTC).isoformat();print(json.dumps(out,indent=2))
