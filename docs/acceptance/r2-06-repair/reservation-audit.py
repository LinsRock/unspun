"""SELECT-only full-window reservation audit on already exposed reviewer challenges."""
import json
from datetime import UTC,datetime
from decimal import Decimal
from pathlib import Path
from sqlalchemy import create_engine,text
from sqlalchemy.orm import Session
from unspun.core.billing import reservation_bound
from unspun.core.content import fingerprint
from unspun.core.member_contracts import REVIEW_PROMPT
from unspun.core.member_recall import current_input,topic_candidate
from unspun.core.sources import load_sources
from unspun.evaluation.member_quality import registration
from unspun.pipeline.member_processing import _prompt_packet
ROOT=Path(__file__).resolve().parents[3];OUT=Path(__file__).parent
execution=json.loads((ROOT/'docs/evaluations/r2/member-retest-v1.json').read_text())
old=registration(require_current_contract=False)
e=create_engine('postgresql+psycopg://unspun:unspun@localhost:5432/unspun_quality_r1_20261016')
rows=[]
with Session(e) as s:
 s.execute(text('SET TRANSACTION READ ONLY'))
 for case in execution['challenges']['cases']:
  t=next(t for t in execution['challenges']['topics'] if t['id']==case['topic_id'])
  original=next(x for x in old['topics'] if x['anchors']==t['anchors'])
  query=current_input(s,case['article_id'],load_sources(),datetime.now(UTC))
  topic=topic_candidate(s,original['id'],load_sources(),datetime.now(UTC));topic['id']=case['topic_id']
  p={'query':query,'candidate':{'topic':topic},'decision_fingerprint':fingerprint(case['decision'])}
  packet=_prompt_packet(p,case['decision'])
  request={'messages':[{'role':'system','content':REVIEW_PROMPT},{'role':'user','content':json.dumps(packet,ensure_ascii=False)}],'max_tokens':4096}
  hold=reservation_bound('google/gemini-2.5-flash',request)
  rows.append({'case':case['id'],'model':'google/gemini-2.5-flash','full_hold_usd':str(hold),'maximum_pool_known_before_call_usd':str(Decimal('0.20')-hold),'minimum_initial_pool_occupancy_usd':str(Decimal('0.01213610')+hold),'request_fingerprint':fingerprint(request)})
value={'at':datetime.now(UTC).isoformat(),'full_output_window_tokens_including_reasoning':66559,'max_tokens_does_not_reduce_original_reservation':True,'old_seven_reservations_unchanged':True,'original_pool_usd':'0.20','previous_pool_spend_usd':'0.01213610','additional_discretionary_future_credit_hold_created':False,'unfrozen_draft_corrected_before_calls':True,'challenges':rows,'interpretation':'Feasible initial prefix only, not a promise that all natural queries and challenges fit. Every actual later request must reserve its full original bound and may stop the batch. No bound or original hold is reduced.','paid_requests':0,'database_writes':0,'blind_materials_read':False}
with (OUT/'reservation-audit.json').open('x') as f:json.dump(value,f,indent=2)
print(json.dumps({'review_full_hold_range':[min(r['full_hold_usd'] for r in rows),max(r['full_hold_usd'] for r in rows)],'paid_requests':0},indent=2))
