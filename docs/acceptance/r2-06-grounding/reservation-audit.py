"""Free complete-window reservation estimates for the exact four audit packets."""
import json
from datetime import UTC,datetime
from decimal import Decimal
from pathlib import Path
from sqlalchemy import text
from sqlalchemy.orm import Session
from unspun.core.billing import reservation_bound
from unspun.core.config import get_settings
from unspun.core.member_contracts import AUDIT_KINDS,AUDIT_PROMPTS,JUDGE_PROMPT,MemberDecision,member_contract
from unspun.core.member_recall import current_input,vector_input
from unspun.core.sources import load_sources
from unspun.core.content import fingerprint
from unspun.core.db import get_engine
from unspun.pipeline import member_processing
ROOT=Path(__file__).resolve().parents[3];OUT=Path(__file__).parent
reg=json.loads((ROOT/'docs/evaluations/r2/member-grounding-challenges-v1.json').read_text());topics={t['id']:t for t in reg['topics']};rows=[]
with Session(get_engine()) as s:
 s.execute(text('SET TRANSACTION READ ONLY'))
 for case in reg['cases']:
  if case.get('pre_llm_failure') or case.get('replay_actual_review_from'):continue
  spec=topics[case['topic_id']];query=current_input(s,case['article_id'],load_sources(),datetime.now(UTC));anchor=current_input(s,spec['anchors'][0],load_sources(),datetime.now(UTC))
  topic={'id':spec['id'],'kind':spec['kind'],'title':spec['title'],'domains':anchor['qualification']['card']['payload']['domains'],'revision':2,'anchors':[{'revision':2,'relation':spec['seed_relation'],'snapshot':anchor}]}
  packet={'query':query,'candidate':{'topic':topic,'vectors':[fingerprint(vector_input(v)) for v in [query,anchor]]},'contract':member_contract()}
  decision=MemberDecision.model_validate(case['decision']);settings=get_settings()
  for kind,system in [('judge',JUDGE_PROMPT),*[(k,AUDIT_PROMPTS[k]) for k in AUDIT_KINDS]]:
   projected=member_processing._prompt_packet(packet,None if kind=='judge' else decision.model_dump(mode='json'),**({} if kind=='judge' else {'kind':kind}))
   request={'messages':[{'role':'system','content':system},{'role':'user','content':json.dumps(projected,ensure_ascii=False)}],'max_tokens':4096}
   model=settings.summary_model if kind=='judge' else settings.viewpoint_model
   hold=reservation_bound(model,request)
   rows.append({'case':case['id'],'kind':kind,'model':model,'input_bytes':sum(len(m['content'].encode()) for m in request['messages']),'complete_hold_usd':str(hold),'is_not_expected_actual_fee':True})
value={'at':datetime.now(UTC).isoformat(),'paid_requests':0,'database_writes':0,'original_full_output_window_including_reasoning':66559,'original_algorithm_unchanged':True,'prior_pool_spend_usd':'0.03171912','pool_cap_usd':'0.30','original_seven_holds_usd':'0.484867','sequential_audits_do_not_sum_all_full_holds_at_once':True,'every_call_rechecks_known_plus_active_hold_against_same_pool':True,'rows':rows,'maximum_review_hold_usd':str(max(Decimal(r['complete_hold_usd']) for r in rows if r['kind']!='judge')),'minimum_review_hold_usd':str(min(Decimal(r['complete_hold_usd']) for r in rows if r['kind']!='judge')),'future_discretionary_reserve_usd':'0','complete_known_plus_hold_at_start_fits':all(Decimal('0.03171912')+Decimal(r['complete_hold_usd'])<=Decimal('0.30') for r in rows)}
with (OUT/'reservation-audit.json').open('x') as f:json.dump(value,f,indent=2)
print({k:v for k,v in value.items() if k!='rows'})
