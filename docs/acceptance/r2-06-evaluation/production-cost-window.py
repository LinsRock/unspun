"""Read-only observed qualified volume and concurrent production fee reconciliation."""
import json
from collections import Counter
from datetime import UTC,datetime,timedelta
from decimal import Decimal
from sqlalchemy import select,text
from sqlalchemy.orm import Session
from unspun.core.content_publication import current_versions,qualified_items
from unspun.core.db import get_engine
from unspun.core.sources import load_sources
START='2026-10-20T11:35:16.244985+00:00'
with get_engine().connect().execution_options(isolation_level='REPEATABLE READ') as c,c.begin():
 c.execute(text('SET TRANSACTION READ ONLY'));s=Session(bind=c);now=c.scalar(text('SELECT transaction_timestamp()'))
 items=qualified_items(s,current_versions(preview=False,as_of=now,sources=load_sources()).subquery())
 eligible=[i for i in items if i.qualification_versions[1]>=now-timedelta(hours=24)]
 calls=[dict(r) for r in c.execute(text('SELECT b.id,b.stage,b.phase,b.article_id,b.source_id,b.status,b.reserved_usd::text,b.started_at,b.ended_at,b.provider_generation_id,u.cost_usd::numeric::text AS known_usd FROM billed_requests b LEFT JOIN llm_usage u ON u.id=b.usage_id WHERE b.started_at>=:start ORDER BY b.started_at,b.id'),{'start':datetime.fromisoformat(START)}).mappings()]
 out={'at':datetime.now(UTC).isoformat(),'window_start':(now-timedelta(hours=24)).isoformat(),'window_end':now.isoformat(),'qualified_current_articles':len(items),'newly_qualified_articles_last_24h':len(eligible),'eligible_ids':[i.article.id for i in eligible],'by_source':dict(Counter(i.article.source_id for i in eligible)),'concurrent_fee_window_start':START,'concurrent_requests':calls,'concurrent_known_usd':str(sum((Decimal(r['known_usd']) for r in calls if r['known_usd'] is not None),Decimal(0))),'concurrent_held_usd':str(sum((Decimal(r['reserved_usd']) for r in calls if r['status'] in ('reserved','usage_unknown')),Decimal(0))),'read_only':True,'paid_requests':0,'interpretation':'Observed eligible production volume, not an authorized automatic topic producer or a stable future forecast.'}
 print(json.dumps(out,default=str,ensure_ascii=False,indent=2))
