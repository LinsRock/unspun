"""SELECT-only production verification; no provider requests or writes."""
import json
from datetime import UTC,datetime
from sqlalchemy import text
from unspun.core.config import get_settings
from unspun.core.db import get_engine
from unspun.core.sources import load_sources
from unspun.pipeline.r1_runtime import build_runtime
settings=get_settings()
runtime=build_runtime(load_sources(),settings)
out={"captured_at":datetime.now(UTC).isoformat(),"configured_synthesis_enabled":getattr(settings,"r2_synthesis_enabled",False),"configured_topic_publication_enabled":getattr(settings,"r2_topic_publication_enabled",False),"configured_member_processing_enabled":settings.r2_member_processing_enabled,"runtime":runtime.describe(),"topic_handlers":[list(k) for k in runtime.handlers if k[1].startswith('topic_')],"tables":{}}
with get_engine().connect() as conn,conn.begin():
    conn.execute(text('SET TRANSACTION READ ONLY'))
    out['read_only']=conn.scalar(text("SELECT current_setting('transaction_read_only')"))
    out['schema']=conn.scalar(text('SELECT version_num FROM alembic_version'))
    for table in ('topics','topic_members','topic_changes','topic_updates','topic_derivations','content_vectors','member_judgments','topic_syntheses'):
        exists=conn.scalar(text('SELECT to_regclass(:table)'),{'table':table}) is not None
        out['tables'][table]={'exists':exists,'rows':conn.scalar(text('SELECT count(*) FROM '+table)) if exists else 0}
    out['topic_tasks']=[dict(r) for r in conn.execute(text("SELECT kind,status,count(*) AS rows FROM pipeline_tasks WHERE kind LIKE 'topic_%' GROUP BY kind,status ORDER BY kind,status")).mappings()]
    out['topic_calls']=[dict(r) for r in conn.execute(text("SELECT stage,status,count(*) AS rows,sum(reserved_usd)::text AS reserved_usd FROM billed_requests WHERE stage LIKE 'topic_%' OR purpose LIKE 'topic_%' GROUP BY stage,status ORDER BY stage,status")).mappings()]
    out['policy']=dict(conn.execute(text('SELECT scope,enabled,monthly_limit_usd::text AS monthly_limit_usd,stage_caps,version FROM budget_policy WHERE id=1')).mappings().one())
out.update(database_writes=0,paid_requests=0,provider_queries=0)
print(json.dumps(out,indent=2,default=str))
