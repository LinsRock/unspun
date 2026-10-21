"""Independent SELECT-only first-label and full-reservation invoice reconciliation."""
import json,hashlib
from collections import Counter
from datetime import UTC,datetime
from decimal import Decimal
from pathlib import Path
from sqlalchemy import select,text
from sqlalchemy.orm import Session
from unspun.core.db import get_engine
from unspun.core.billing_models import BilledRequest
from unspun.core.models import LlmUsage
from unspun.core.task_models import PipelineTask,TaskAttempt
from unspun.core.llm import parse_json_content
from unspun.evaluation.member_quality import registration,batch_state,require_original_database
from unspun.evaluation.member_retest import ROOT,EVIDENCE,load_execution
require_original_database();execution=load_execution();out=EVIDENCE
report=json.load(open(out/'results-v1.json'));expected={'regression':{q['article_id']:q['expected_associations'] for q in registration(require_current_contract=False)['queries']}}
specs={'regression':registration(require_current_contract=False)}
workers={'regression':execution['id']+':regression','challenge':execution['challenges']['id']}
seal=json.load(open(ROOT/execution['blind_seal']));workers['blind']=seal['id']
if report['phases']['blind'].get('metrics') is not None:
 spec=json.load(open(Path(seal['sealed_directory'])/'registration.json'));specs['blind']=spec;expected['blind']={q['article_id']:q['expected_associations'] for q in spec['queries']}
with Session(get_engine()) as s:
 s.execute(text('SET TRANSACTION READ ONLY'))
 attempt_workers={a.id:a.worker for a in s.scalars(select(TaskAttempt))}
 bills=[b for b in s.scalars(select(BilledRequest).order_by(BilledRequest.started_at,BilledRequest.id)) if attempt_workers.get(b.task_attempt_id) in set(workers.values())]
 usage={u.id:u for u in s.scalars(select(LlmUsage))};tasks={t.id:t for t in s.scalars(select(PipelineTask))}
 prefix=Decimal('0.01213610');peak=prefix;fees=Decimal(0);provider_ids=[];per_stage=Counter();rows=[]
 stage_prefix={'topic_embedding':Decimal('0.00014500'),'topic_judgment':Decimal('0.01199110'),'topic_review':Decimal(0)}
 for b in bills:
  peak=max(peak,prefix+b.reserved_usd);assert prefix+b.reserved_usd<=Decimal('0.20')
  assert stage_prefix[b.stage]+b.reserved_usd<=Decimal(execution['budget']['stage_caps_usd'][b.stage])
  known=Decimal(str(usage[b.usage_id].cost_usd)) if b.usage_id else None
  if known is not None:
   assert known<=b.reserved_usd and known==Decimal(str(b.response_payload['usage']['cost']))
   prefix+=known;fees+=known;stage_prefix[b.stage]+=known
  if b.provider_generation_id:provider_ids.append(b.provider_generation_id)
  per_stage[b.stage]+=1
  rows.append({'id':b.id,'provider_id':b.provider_generation_id,'task':b.task_id,'attempt':b.task_attempt_id,'worker':attempt_workers[b.task_attempt_id],'article_id':b.article_id,'source_id':b.source_id,'stage':b.stage,'phase':b.phase,'requested_model':b.model,'provider_model':b.response_payload.get('model') if b.response_payload else None,'status':b.status,'price_version':b.price_version,'complete_reserved_usd':str(b.reserved_usd),'known_paid_usd':str(known) if known is not None else None})
 assert len(provider_ids)==len(set(provider_ids))
 qchecks={}
 for phase,spec in specs.items():
  topic_keys={t['id']:t['key'] for t in spec['topics']}
  if phase=='regression':
   from uuid import uuid5,NAMESPACE_URL
   topic_keys={str(uuid5(NAMESPACE_URL,workers[phase]+':'+t['key'])):t['key'] for t in spec['topics']}
  groups={}
  for b in bills:
   if b.stage=='topic_judgment' and attempt_workers[b.task_attempt_id]==workers[phase]:groups.setdefault(b.task_id,[]).append(b)
  n=correct=accuracy=negative=fp=0
  for taskid,bs in groups.items():
   t=tasks[taskid];allowed=expected[phase][t.article_id].get(topic_keys[t.payload['candidate']['topic']['id']],[])
   try:raw=parse_json_content(bs[0].response_payload['choices'][0]['message']['content'])
   except (ValueError,TypeError,KeyError,IndexError):raw={}
   assoc=raw.get('certainty')=='certain' and raw.get('classification')!='independent'
   n+=assoc;correct+=assoc and raw.get('classification') in allowed
   accuracy+=bool(raw and ((assoc and raw.get('classification') in allowed) if allowed else (raw.get('classification')=='independent' or raw.get('certainty')=='uncertain')))
   negative+=not bool(allowed);fp+=not allowed and assoc
  m=report['phases'][phase]['metrics']
  assert (correct,n)==(m['judgment_precision']['numerator'],m['judgment_precision']['denominator'])
  assert (accuracy,len(groups))==(m['raw_accuracy']['numerator'],m['raw_accuracy']['denominator'])
  assert (fp,negative)==(m['raw_false_associations_among_negative_pairs']['numerator'],m['raw_false_associations_among_negative_pairs']['denominator'])
  qchecks[phase]={'first_association_precision':{'numerator':correct,'denominator':n},'all_first_label_accuracy':{'numerator':accuracy,'denominator':len(groups)},'raw_negative_false_positive':{'numerator':fp,'denominator':negative}}
 state=batch_state(s);assert state['physical_requests']==59+len(bills)
 assert abs(Decimal(state['known_usd'])-prefix)<Decimal('0.0000000001')
 assert len(bills)<=121 and state['physical_requests']<=180
 for phase,worker in workers.items():assert sum(attempt_workers[b.task_attempt_id]==worker for b in bills)<=execution['phases'][phase if phase!='challenge' else 'challenge']['physical_request_limit']
 original_ids=[h['id'] for h in execution['original_holds']]
 holds=[dict(r) for r in s.execute(text("SELECT id,status,reserved_usd::text,provider_generation_id FROM billed_requests WHERE id=ANY(:ids) ORDER BY id"),{'ids':original_ids}).mappings()]
 assert holds==execution['original_holds']
 value={'at':datetime.now(UTC).isoformat(),'independent_assertions_passed':True,'new_physical_requests':len(bills),'provider_ids_present':len(provider_ids),'stage_counts':dict(per_stage),'new_known_usd':str(fees),'previous_r206_known_usd':'0.01213610','cumulative_r206_known_usd':str(prefix),'pool_limit_usd':'0.20','peak_known_plus_complete_next_reservation_usd':str(peak),'stage_known_usd':{k:str(v) for k,v in stage_prefix.items()},'original_seven_holds_unchanged':True,'original_held_usd':'0.484867','independent_raw_quality':qchecks,'paid_requests_from_audit':0,'database_writes':0,'blind_unused_materials_opened':report['phases']['blind'].get('metrics') is not None,'per_call':rows}
 with (out/'fee-reconciliation.json').open('x') as f:json.dump(value,f,indent=2)
 print(json.dumps({k:v for k,v in value.items() if k!='per_call'},indent=2))
