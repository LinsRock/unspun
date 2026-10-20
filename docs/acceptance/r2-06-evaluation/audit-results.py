"""Independent SELECT-only denominator, invoice-envelope and provider reconciliation."""
import hashlib
import json
from datetime import UTC,datetime
from decimal import Decimal
from pathlib import Path
from sqlalchemy import select,text
from sqlalchemy.orm import Session
from unspun.core.billing_models import BilledRequest
from unspun.core.db import get_engine
from unspun.core.llm import parse_json_content
from unspun.core.models import LlmUsage
from unspun.core.task_models import PipelineTask
from unspun.evaluation.member_quality import registration,require_original_database
OUT=Path(__file__).parent;require_original_database();spec=registration()
result=json.loads((OUT/'results-v1.json').read_text());expected={q['article_id']:q['expected_associations'] for q in spec['queries']};topic_names={t['id']:t['key'] for t in spec['topics']}
with Session(get_engine()) as s:
 s.connection().exec_driver_sql('SET TRANSACTION READ ONLY')
 rows=list(s.execute(select(BilledRequest,PipelineTask,LlmUsage).join(PipelineTask,BilledRequest.task_id==PipelineTask.id).join(LlmUsage,BilledRequest.usage_id==LlmUsage.id).where(BilledRequest.stage.in_(['topic_embedding','topic_judgment','topic_review'])).order_by(BilledRequest.started_at,BilledRequest.id)))
 certain=correct=right=negative=false_positive=0
 prefix=Decimal(0);peak=Decimal(0);stages={};stage_spend={};stage_peaks={};ids=set();provider_ids=0
 for bill,task,usage in rows:
  assert bill.id not in ids and bill.status=='responded' and bill.http_status==200
  ids.add(bill.id);provider_ids+=bill.provider_generation_id is not None
  cost=Decimal(str(usage.cost_usd));assert cost<=bill.reserved_usd
  peak=max(peak,prefix+bill.reserved_usd);prefix+=cost
  stage_peaks[bill.stage]=max(stage_peaks.get(bill.stage,Decimal(0)),stage_spend.get(bill.stage,Decimal(0))+bill.reserved_usd)
  stage_spend[bill.stage]=stage_spend.get(bill.stage,Decimal(0))+cost;stages[bill.stage]=stages.get(bill.stage,0)+1
  if bill.stage!='topic_judgment':continue
  raw=parse_json_content(bill.response_payload['choices'][0]['message']['content'])
  allowed=expected[task.article_id].get(topic_names[task.payload['candidate']['topic']['id']],[])
  associated=raw['certainty']=='certain' and raw['classification']!='independent'
  certain+=associated;correct+=associated and raw['classification'] in allowed
  negative+=not allowed;false_positive+=not allowed and associated
  right+=(associated and raw['classification'] in allowed) if allowed else not associated
 assert (len(rows),certain,correct,right,negative,false_positive)==(59,8,5,37,34,2)
 assert result['metrics']['judgment_precision']=={'numerator':5,'denominator':8,'value':.625}
 assert result['new_known_usd']==str(prefix)
 assert peak<=Decimal('0.20')
 assert all(stage_peaks[k]<=Decimal(spec['budget']['stage_caps_usd'][k]) for k in stage_peaks)
 assert all(stages.get(k,0)<=v for k,v in spec['budget']['stage_physical_limits'].items())
 before=json.loads((OUT/'prepay-evaluation.json').read_text());after=json.loads((OUT/'postdeploy-evaluation.json').read_text())
 assert before['unknown_requests']==after['unknown_requests'] and len(after['unknown_requests'])==7
 old_known=Decimal(before['known_ledger'][0]['known_usd']);after_known=Decimal(after['known_ledger'][0]['known_usd'])
 assert after_known-old_known==prefix
 assert old_known+Decimal('0.484867')+peak<=Decimal('1.50')
 pre_prod=json.loads((OUT/'predeploy-production.json').read_text());post_prod=json.loads((OUT/'postdeploy-production.json').read_text())
 natural=json.loads((OUT/'production-window-after-paid.json').read_text())
 provider_delta=Decimal(str(post_prod['provider']['usage']))-Decimal(str(pre_prod['provider']['usage']))
 prod_delta=Decimal(post_prod['known_ledger'][0]['known_usd'])-Decimal(pre_prod['known_ledger'][0]['known_usd'])
 assert prod_delta==Decimal(natural['concurrent_known_usd'])
 assert provider_delta==prod_delta+prefix
 report={'at':datetime.now(UTC).isoformat(),'all_independent_assertions_passed':True,'physical_requests':len(rows),'provider_ids_present':provider_ids,'stage_counts':stages,'known_new_usd':str(prefix),'new_held_usd':'0','original_unknown_count':7,'original_held_usd':'0.484867','evaluation_known_before_usd':str(old_known),'evaluation_known_after_usd':str(after_known),'evaluation_known_plus_holds_usd':str(after_known+Decimal('0.484867')),'evaluation_remaining_usd':str(Decimal('1.50')-after_known-Decimal('0.484867')),'peak_batch_known_plus_one_full_reservation_usd':str(peak),'stage_peak_envelopes_usd':{k:str(v) for k,v in stage_peaks.items()},'batch_cap_usd':'0.20','provider_delta_usd':str(provider_delta),'concurrent_production_known_usd':str(prod_delta),'provider_delta_matches_natural_production_plus_this_batch':True,'raw_classification_precision':{'numerator':correct,'denominator':certain},'raw_accuracy':{'numerator':right,'denominator':40},'raw_false_positive_rate':{'numerator':false_positive,'denominator':negative},'first_run_sha256':hashlib.sha256((OUT/'first-run.ndjson').read_bytes()).hexdigest(),'paid_requests_from_this_audit':0,'database_writes':0}
with (OUT/'fee-reconciliation.json').open('x') as f:json.dump(report,f,indent=2)
print(json.dumps(report,indent=2))
