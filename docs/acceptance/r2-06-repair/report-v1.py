"""SELECT-only first-output quality, real review/CAS and invoice report for the frozen retest."""
import gzip,hashlib,json
from collections import Counter
from datetime import UTC,datetime
from decimal import Decimal
from pathlib import Path
from pydantic import ValidationError
from sqlalchemy import select,text
from sqlalchemy.orm import Session
from unspun.core.billing import reservation_bound
from unspun.core.content import fingerprint
from unspun.core.llm import parse_json_content
from unspun.core.member_contracts import MemberDecision,MemberReview,JUDGE_PROMPT,REVIEW_PROMPT
from unspun.core.member_models import MemberJudgment,ContentVector
from unspun.core.member_recall import validate_decision
from unspun.core.models import LlmUsage
from unspun.core.billing_models import BilledRequest
from unspun.core.task_models import PipelineTask,TaskAttempt
from unspun.core.topic_models import Topic
from unspun.evaluation.member_quality import require_original_database,batch_state
from unspun.evaluation.member_retest import ROOT,EVIDENCE,load_execution,phase_spec
from unspun.core.db import get_engine
from unspun.pipeline.member_processing import _prompt_packet
require_original_database();execution=load_execution();engine=get_engine();OUT=EVIDENCE
seal=json.loads((ROOT/execution['blind_seal']).read_text())
def ratio(n,d):return {'numerator':n,'denominator':d,'value':n/d if d else None}
def write(name,value):
 with (OUT/name).open('x') as f:json.dump(value,f,indent=2,ensure_ascii=False,default=str)
def raw(bill):
 try:return parse_json_content(bill.response_payload['choices'][0]['message']['content'])
 except (KeyError,IndexError,TypeError,ValueError):return None
specs={'regression':phase_spec(execution,'regression')}
# Never open an unused holdout just to produce a report after an earlier guard halt.
if (OUT/'blind-first-run.ndjson').exists():
 directory=Path(seal['sealed_directory'])
 for row in seal['files']:assert hashlib.sha256((directory/row['path']).read_bytes()).hexdigest()==row['sha256']
 spec=json.loads((directory/'registration.json').read_text());specs['blind']={**spec,'contract':execution['contract'],'budget':execution['budget']}
with engine.connect() as conn,conn.begin():
 conn.execute(text('SET TRANSACTION READ ONLY'));s=Session(bind=conn)
 all_tasks=list(s.scalars(select(PipelineTask).order_by(PipelineTask.id)))
 judgments={j.input_fingerprint:j for j in s.scalars(select(MemberJudgment))}
 all_bills=list(s.scalars(select(BilledRequest).order_by(BilledRequest.started_at,BilledRequest.id)))
 usage={u.id:u for u in s.scalars(select(LlmUsage))}
 attempts=list(s.scalars(select(TaskAttempt)))
 phase_by_attempt={a.id:a.worker for a in attempts}
 phase_reports={};phase_bills={};all_pairs=[];all_expected=[];successful_chains=[]
 for phase,spec in specs.items():
  records=[json.loads(line) for line in (OUT/(phase+'-first-run.ndjson')).read_text().splitlines()]
  started={r['article_id']:r for r in records if r['event']=='query'}
  names={t['id']:t['key'] for t in spec['topics']};ids=set(names)
  queries={q['article_id']:q for q in spec['queries']}
  tasks=[t for t in all_tasks if t.strategy_version==execution['contract']['version'] and ((t.kind=='topic_recall' and t.payload.get('trace',{}).get('topic_scope')==sorted(ids)) or (t.kind in ['topic_judge','topic_review'] and t.payload.get('candidate',{}).get('topic',{}).get('id') in ids))]
  bills=[b for b in all_bills if phase_by_attempt.get(b.task_attempt_id)==spec['id']];phase_bills[phase]=bills
  pairs=[]
  for task in tasks:
   if task.kind!='topic_judge':continue
   key=names[task.payload['candidate']['topic']['id']];allowed=queries[task.article_id]['expected_associations'].get(key,[])
   calls=[b for b in bills if b.task_id==task.id];first=raw(calls[0]) if calls else None
   schema=False;refs=False;schema_error=None;refs_error=None
   if first is not None:
    try:
     dec=MemberDecision.model_validate(first);schema=True
     try:validate_decision(s,task.payload,dec);refs=True
     except (ValueError,KeyError,TypeError) as e:refs_error=str(e)
    except ValidationError as e:schema_error=str(e)
   associated=bool(first and first.get('certainty')=='certain' and first.get('classification')!='independent')
   correct=bool(first and ((associated and first.get('classification') in allowed) if allowed else (first.get('classification')=='independent' or first.get('certainty')=='uncertain')))
   j=judgments.get(task.input_fingerprint);applied=bool(j and j.status=='applied')
   final=j.decision if j else None
   correct_applied=bool(applied and final and final['classification'] in allowed)
   review_tasks=[t for t in tasks if t.kind=='topic_review' and t.payload.get('decision_key')==task.input_fingerprint]
   review=j.review if j else None
   pairs.append({'article_id':task.article_id,'topic':key,'task_id':task.id,'task_status':task.status,'allowed':allowed,'association_expected':bool(allowed),'raw_first':first,'physical_calls':len(calls),'schema_valid':schema,'schema_error':schema_error,'reference_valid':refs,'reference_error':refs_error,'associated':associated,'raw_correct':correct,'operationally_correct':bool(correct and schema and refs and j),'final_decision':final,'judgment_status':j.status if j else None,'applied':applied,'correct_applied':correct_applied,'review':review,'review_task_ids':[t.id for t in review_tasks],'review_statuses':[t.status for t in review_tasks]})
  expected=[];layers=Counter()
  for q in spec['queries']:
   event=started.get(q['article_id']);plan=event['plan'] if event else None;trace=plan['trace'] if plan else None
   if trace:
    layers['domain_pairs']+=trace['domain_topics']-len(trace['existing_member_topics'])
    layers['sql32_pairs']+=len(trace['scanned_topic_ids']);layers['valid_anchor_pairs']+=len(trace['qualified_topic_ids']);layers['metadata12_pairs']+=len(trace['metadata_topic_ids'])
   for key,allowed in q['expected_associations'].items():
    target=next(t['id'] for t in spec['topics'] if t['key']==key);loss=None
    if event is None:loss='not_started_after_guard'
    elif target in trace['existing_member_topics']:loss='already_decided_in_registered_pool'
    elif target not in trace['scanned_topic_ids']:
     topic=s.get(Topic,target);domains=set(plan['query']['qualification']['card']['payload']['domains'])
     loss='sql32' if topic and domains.intersection(topic.domains) else 'domain'
    elif target not in trace['qualified_topic_ids']:loss='valid_anchor32'
    elif target not in trace['metadata_topic_ids']:loss='metadata12'
    elif not any(p['article_id']==q['article_id'] and p['topic']==key for p in pairs):loss='vector4_or_recall_execution'
    expected.append({'article_id':q['article_id'],'topic':key,'allowed':allowed,'first_recall_loss':loss})
  attempted=[p for p in pairs if p['physical_calls']];outputs=[p for p in attempted if p['raw_first'] is not None];assoc=[p for p in attempted if p['associated']];applied=[p for p in pairs if p['applied']];negative=[p for p in attempted if not p['association_expected']]
  reviewed=[p for p in pairs if p['review'] is not None];bad_reviewed=[p for p in reviewed if p['final_decision']['classification'] not in p['allowed']]
  metrics={'candidate_recall':ratio(sum(e['first_recall_loss'] is None for e in expected),len(expected)),'candidate_recall_for_started_queries':ratio(sum(e['first_recall_loss'] is None for e in expected if e['article_id'] in started),sum(e['article_id'] in started for e in expected)),'judgment_precision':ratio(sum(p['raw_correct'] for p in assoc),len(assoc)),'raw_accuracy':ratio(sum(p['raw_correct'] for p in attempted),len(attempted)),'schema_valid_first_outputs':ratio(sum(p['schema_valid'] for p in attempted),len(attempted)),'valid_reference_among_schema_valid':ratio(sum(p['reference_valid'] for p in attempted),sum(p['schema_valid'] for p in attempted)),'operational_accuracy':ratio(sum(p['operationally_correct'] for p in attempted),len(attempted)),'final_correct_member_coverage':ratio(sum(p['correct_applied'] for p in applied),len(expected)),'all_incorrect_writes_among_applied':ratio(sum(not p['correct_applied'] for p in applied),len(applied)),'wrong_relation_among_applied_expected_pairs':ratio(sum(p['association_expected'] and not p['correct_applied'] for p in applied),sum(p['association_expected'] for p in applied)),'false_merges_among_attempted_negative_pairs':ratio(sum(p['applied'] for p in negative),len(negative)),'raw_false_associations_among_negative_pairs':ratio(sum(p['associated'] for p in negative),len(negative)),'review_rejection':ratio(sum(p['judgment_status']=='rejected' for p in reviewed),len(reviewed)),'wrong_decision_review_interception':ratio(sum(p['judgment_status']=='rejected' for p in bad_reviewed),len(bad_reviewed)),'stale_cas':sum(p['judgment_status']=='stale' for p in pairs),'unprocessed_selected_pairs':sum(not p['physical_calls'] for p in pairs),'no_parseable_first_output':sum(p['raw_first'] is None for p in attempted),'structure_failures_with_response':sum(not p['schema_valid'] for p in attempted if p['raw_first'] is not None),'task_statuses':dict(Counter(t.status for t in tasks))}
  costs={}
  for stage in ['topic_embedding','topic_judgment','topic_review']:
   bs=[b for b in bills if b.stage==stage];known=sum((Decimal(str(usage[b.usage_id].cost_usd)) for b in bs if b.usage_id),Decimal(0))
   costs[stage]={'physical_requests':len(bs),'known_usd':str(known),'held_usd':str(sum((b.reserved_usd for b in bs if b.status in ['reserved','usage_unknown']),Decimal(0))),'per_physical_request_usd':str(known/len(bs)) if bs else None}
  for q in spec['queries']:
   ps=[p for p in pairs if p['article_id']==q['article_id']];correct_members=[p for p in ps if p['correct_applied']]
   if correct_members and set(q['expected_associations'])=={p['topic'] for p in correct_members} and all(p['task_status']=='completed' for p in ps) and not any(p['applied'] and not p['correct_applied'] for p in ps):
    bs=[b for b in bills if b.article_id==q['article_id']];known=sum((Decimal(str(usage[b.usage_id].cost_usd)) for b in bs if b.usage_id),Decimal(0))
    successful_chains.append({'phase':phase,'article_id':q['article_id'],'correct_members':len(correct_members),'physical_requests':len(bs),'incremental_complete_query_cost_usd':str(known),'cache_state':'warm' if not any(b.stage=='topic_embedding' for b in bs) else 'includes_cold_vectors','includes_all_negative_candidate_calls':True})
  phase_reports[phase]={'registration_id':spec['id'],'last_event':records[-1]['event'],'halt':records[-1] if records[-1]['event']=='halt' else None,'registered_queries':len(spec['queries']),'started_queries':len(started),'unavailable_inputs':spec.get('unavailable_inputs',[]),'expected_pairs':len(expected),'selected_pairs':len(pairs),'metrics':metrics,'layers':dict(layers),'expected_pair_losses':expected,'candidate_results':pairs,'costs':costs,'warm_vector_versions_present_before_recall':sum(len(r['vector_cache_before']['warm_keys']) for r in started.values()),'unique_vector_versions_planned_across_queries':sum(r['vector_cache_before']['unique_inputs'] for r in started.values()),'retries':sum(max(0,p['physical_calls']-1) for p in pairs)}
  all_pairs+=pairs;all_expected+=expected
 if 'blind' not in phase_reports:phase_reports['blind']={'status':'not_executed_and_still_sealed','registered_queries':seal['counts']['registered_queries'],'expected_pairs':seal['counts']['expected_association_pairs'],'metrics':None,'reason':'Earlier frozen execution did not complete; no paid blind material consumed and no root unblinding.'}
 cbills=[b for b in all_bills if phase_by_attempt.get(b.task_attempt_id)==execution['challenges']['id']]
 challenges=[]
 for c in execution['challenges']['cases']:
  js=[j for j in judgments.values() if j.topic_id==c['topic_id']]
  challenges.append({'id':c['id'],'expected_status':c['expected_final_status'],'actual_status':js[0].status if js else None,'review':js[0].review if js else None,'natural_end_to_end':False})
 totals=batch_state(s);original_holds=[dict(r) for r in s.execute(text("SELECT id,status,reserved_usd::text,provider_generation_id FROM billed_requests WHERE status IN ('reserved','usage_unknown') ORDER BY id")).mappings()]
 newbills=[b for rows in phase_bills.values() for b in rows]+cbills
 known=sum((Decimal(str(usage[b.usage_id].cost_usd)) for b in newbills if b.usage_id),Decimal(0));prefix=Decimal('0.01213610');peak=prefix
 for b in sorted(newbills,key=lambda b:(b.started_at,b.id)):
  peak=max(peak,prefix+b.reserved_usd)
  if b.usage_id:prefix+=Decimal(str(usage[b.usage_id].cost_usd))
 old_hold_ids={h['id'] for h in execution['original_holds']}
 retained_holds=[h for h in original_holds if h['id'] in old_hold_ids]
 new_holds=[h for h in original_holds if h['id'] not in old_hold_ids]
 assert peak<=Decimal('0.20') and retained_holds==execution['original_holds']
 blocked=[]
 for t in all_tasks:
  if t.status!='budget_deferred' or t.strategy_version!=execution['contract']['version']:continue
  j=judgments.get(t.payload.get('decision_key'));draft=j.decision if j else None
  if t.kind in ['topic_judge','topic_review']:
   packet=_prompt_packet(t.payload,draft);req={'messages':[{'role':'system','content':REVIEW_PROMPT if draft is not None else JUDGE_PROMPT},{'role':'user','content':json.dumps(packet,ensure_ascii=False)}],'max_tokens':4096}
   hold=reservation_bound('google/gemini-2.5-flash' if draft is not None else 'google/gemini-2.5-flash-lite',req)
   blocked.append({'task_id':t.id,'kind':t.kind,'last_error':t.last_error,'next_full_reservation_usd':str(hold),'pool_known_usd':totals['known_usd'],'would_occupy_usd':str(Decimal(totals['known_usd'])+hold),'pool_cap_usd':'0.20','paid_request_for_blocked_attempt':any(b.task_id==t.id for b in newbills)})
 report={'schema_version':'r206-retest-results-v1','at':datetime.now(UTC).isoformat(),'source_freeze_sha256':hashlib.sha256((ROOT/'docs/evaluations/r2/member-repair-freeze-v1.json').read_bytes()).hexdigest(),'phases':phase_reports,'separate_review_challenges':{'results':challenges,'physical_review_requests':len(cbills),'mixed_into_natural_metrics':False},'successful_complete_chains':successful_chains,'new_physical_requests':len(newbills),'new_known_usd':str(known),'cumulative_r206_pool':totals,'peak_pool_known_plus_full_next_reservation_usd':str(peak),'original_holds_unchanged':True,'new_unresolved_holds':new_holds,'original_hold_usd':str(sum((Decimal(h['reserved_usd']) for h in retained_holds),Decimal(0))),'blocked_before_http':blocked,'cold_vector_cost_this_retest':{'physical_requests':sum(b.stage=='topic_embedding' for b in newbills),'known_usd':str(sum((Decimal(str(usage[b.usage_id].cost_usd)) for b in newbills if b.stage=='topic_embedding' and b.usage_id),Decimal(0))),'unmeasured_if_no_requests':not any(b.stage=='topic_embedding' for b in newbills)},'missing_real_dimensions':seal['missing_or_unmeasured_dimensions'],'overall_technical_pass':False,'user_acceptance':None,'production_enabled':False,'source_or_prompt_tuning_after_first_output':False,'first_run_hashes':{phase:hashlib.sha256((OUT/(phase+'-first-run.ndjson')).read_bytes()).hexdigest() for phase in ['regression','blind','challenge'] if (OUT/(phase+'-first-run.ndjson')).exists()}}
 write('results-v1.json',report)
 export=[('physical-requests',[dict(s.execute(select(BilledRequest.__table__).where(BilledRequest.id==b.id)).mappings().one())|{'known_cost_usd':str(usage[b.usage_id].cost_usd) if b.usage_id else None} for b in newbills]),('tasks',[dict(r) for r in s.execute(select(PipelineTask.__table__).where(PipelineTask.strategy_version==execution['contract']['version'])).mappings()]),('attempts',[dict(r) for r in s.execute(select(TaskAttempt.__table__).where(TaskAttempt.task_id.in_([t.id for t in all_tasks if t.strategy_version==execution['contract']['version']]))).mappings()]),('judgments',[dict(r) for r in s.execute(select(MemberJudgment.__table__).where(MemberJudgment.task_id.in_([t.id for t in all_tasks if t.strategy_version==execution['contract']['version']]))).mappings()]),('vectors',[dict(r) for r in s.execute(select(ContentVector.__table__)).mappings()])]
 for name,rows in export:
  with gzip.open(OUT/(name+'.json.gz'),'xt') as f:json.dump(rows,f,ensure_ascii=False,default=str)
print(json.dumps({'metrics':{p:r.get('metrics') for p,r in phase_reports.items()},'new_known_usd':str(known),'new_physical_requests':len(newbills),'blocked_before_http':blocked,'successful_chains':len(successful_chains)},indent=2))
