"""SELECT-only first-output and complete-audit report; strict findings are a separate review."""
import gzip,hashlib,json
from collections import Counter,defaultdict
from datetime import UTC,datetime
from decimal import Decimal
from pathlib import Path
from pydantic import ValidationError
from sqlalchemy import select,text
from sqlalchemy.orm import Session
from unspun.core.billing import provider_cap,reservation_bound
from unspun.core.billing_models import BilledRequest
from unspun.core.content import fingerprint
from unspun.core.db import get_engine
from unspun.core.llm import parse_json_content
from unspun.core.member_contracts import AUDIT_KINDS,AUDIT_PROMPTS,JUDGE_PROMPT,MemberDecision,MemberAudit,MemberReview,member_contract
from unspun.core.member_evidence import audit_supported,audit_targets,review_binding,review_supported
from unspun.core.member_models import ContentVector,MemberJudgment
from unspun.core.member_recall import validate_decision,vector_input
from unspun.core.models import LlmUsage
from unspun.core.task_models import PipelineTask,TaskAttempt
from unspun.evaluation.member_quality import require_original_database,batch_state
from unspun.evaluation.member_grounding import ROOT,EVIDENCE,FREEZE,load_execution,exposed_spec,scoped_tasks
from unspun.pipeline import member_processing
require_original_database();exe=load_execution();OUT=EVIDENCE

def ratio(n,d):return {'numerator':n,'denominator':d,'value':n/d if d else None}
def raw(bill):
 try:return parse_json_content(bill.response_payload['choices'][0]['message']['content'])
 except (KeyError,IndexError,TypeError,ValueError):return None

def write(name,value):
 with (OUT/name).open('x') as f:json.dump(value,f,indent=2,ensure_ascii=False,default=str)

def export(name,value):
 with (OUT/name).open('xb') as stream:
  with gzip.GzipFile(fileobj=stream,mode='wb',mtime=0) as f:f.write(json.dumps(value,ensure_ascii=False,default=str).encode())

def requests_for(task,draft):
 variants=[]
 if task.kind=='topic_recall':
  for snap in [task.payload['query'],*[a['snapshot'] for t in task.payload['topics'] for a in t['anchors']]]:
   v=vector_input(snap)
   payload={'model':v['model'],'input':[v['text']],'dimensions':v['dimensions'],'provider':provider_cap(v['model'])}
   variants.append(('embed',payload))
 else:
  for kind in (AUDIT_KINDS if draft is not None else ('judge',)):
   packet=member_processing._prompt_packet(task.payload,draft,**({} if kind=='judge' else {'kind':kind}))
   model=exe['contract']['judgment_model'] if kind=='judge' else exe['contract']['review_model']
   for tokens in (4096,8192):
    payload={'model':model,'messages':[{'role':'system','content':JUDGE_PROMPT if kind=='judge' else AUDIT_PROMPTS[kind]},{'role':'user','content':json.dumps(packet,ensure_ascii=False)}],'response_format':{'type':'json_object'},'usage':{'include':True},'max_tokens':tokens,'temperature':0,'provider':provider_cap(model)}
    variants.append((kind,payload))
 return {fingerprint(p):(k,p) for k,p in variants}

specs={'exposed':exposed_spec(exe)}
if (OUT/'blind-first-run.ndjson').exists():
 seal=json.loads((ROOT/exe['new_blind_seal']).read_text());directory=Path(seal['sealed_directory'])
 spec=json.loads((directory/'registration.json').read_text());specs['blind']={**spec,'contract':exe['contract'],'budget':exe['budget']}
with get_engine().connect() as connection,connection.begin():
 connection.execute(text('SET TRANSACTION READ ONLY'));s=Session(bind=connection)
 tasks={t.id:t for t in s.scalars(select(PipelineTask))}
 attempts={a.id:a for a in s.scalars(select(TaskAttempt))}
 usages={u.id:u for u in s.scalars(select(LlmUsage))}
 judgments={j.task_id:j for j in s.scalars(select(MemberJudgment))}
 all_bills=list(s.scalars(select(BilledRequest).order_by(BilledRequest.started_at,BilledRequest.id)))
 bills=[b for b in all_bills if b.task_attempt_id in attempts and attempts[b.task_attempt_id].worker.startswith(exe['id']+':')]
 reconstruction=[];bill_kinds={};reconstruction_failures=[]
 for bill in bills:
  task=tasks[bill.task_id];draft=judgments.get(task.payload.get('decision_key'))
  if task.kind=='topic_review':
   row=s.get(MemberJudgment,task.payload['decision_key']);draft=row.decision if row else None
  else:draft=None
  variants=requests_for(task,draft)
  match=variants.get(bill.request_fingerprint)
  if match is None:reconstruction_failures.append(bill.id);continue
  kind,request=match;bill_kinds[bill.id]=kind
  assert reservation_bound(bill.model,request)==bill.reserved_usd
  reconstruction.append({'request_id':bill.id,'kind':kind,'original_request_fingerprint':bill.request_fingerprint,'reconstructed_request_matches':True,'request':request,'reconstruction_origin':'Exact frozen code + immutable task/decision, checked against original billed hash; Authorization is never stored.'})
 phase_reports={}
 for phase,spec in specs.items():
  path=OUT/(phase+'-first-run.ndjson')
  if not path.exists():phase_reports[phase]={'status':'not_executed','registered_queries':len(spec['queries']),'metrics':None};continue
  records=[json.loads(line) for line in path.read_text().splitlines()]
  queries={q['article_id']:q for q in spec['queries']};names={t['id']:t['key'] for t in spec['topics']}
  started={r['article_id']:r for r in records if r['event']=='query'}
  worker=spec['id'];bs=[b for b in bills if attempts[b.task_attempt_id].worker==worker]
  ts=scoped_tasks(s,spec);pairs=[]
  for task in ts:
   if task.kind!='topic_judge':continue
   key=names[task.payload['candidate']['topic']['id']];allowed=queries[task.article_id]['expected_associations'].get(key,[])
   calls=[b for b in bs if b.task_id==task.id];first=raw(calls[0]) if calls else None
   schema=refs=False;schema_error=ref_error=None;decision=None
   if first is not None:
    try:
     decision=MemberDecision.model_validate(first);schema=True
     try:validate_decision(s,task.payload,decision);refs=True
     except (ValueError,KeyError,TypeError) as error:ref_error=str(error)
    except ValidationError as error:schema_error=str(error)
   assoc=bool(first and first.get('certainty')=='certain' and first.get('classification')!='independent')
   label_correct=bool(first and ((assoc and first.get('classification') in allowed) if allowed else (first.get('classification')=='independent' or first.get('certainty')=='uncertain')))
   row=judgments.get(task.id);review_tasks=[t for t in ts if t.kind=='topic_review' and t.payload['decision_key']==task.input_fingerprint]
   review_calls=[b for b in bs if b.task_id in {t.id for t in review_tasks}]
   applied=bool(row and row.status=='applied');protocol=bool(row and row.review and decision and review_supported(row.input_snapshot,decision,MemberReview.model_validate(row.review)))
   pairs.append({'article_id':task.article_id,'topic':key,'judge_task_id':task.id,'judgment_fingerprint':task.input_fingerprint,'allowed':allowed,'association_expected':bool(allowed),'first_output':first,'judge_status':task.status,'schema_valid':schema,'reference_valid':refs,'schema_error':schema_error,'reference_error':ref_error,'associated':assoc,'label_correct':label_correct,'judgment_status':row.status if row else None,'applied':applied,'label_compatible_applied':bool(applied and row.decision['classification'] in allowed),'review':row.review if row else None,'complete_bound_audit_protocol_pass':protocol,'review_task_ids':[t.id for t in review_tasks],'real_audit_http_calls':len(review_calls),'actual_audit_kinds':[bill_kinds.get(b.id) for b in review_calls],'review_task_statuses':[t.status for t in review_tasks],'basis':decision.basis if decision else None})
  expected=[];layers=Counter();warm_occurrences=0;warm_union=set()
  for q in spec['queries']:
   event=started.get(q['article_id']);trace=event['plan']['trace'] if event else None
   if event:
    warm_occurrences+=len(event['vector_cache_before']['warm_keys']);warm_union.update(event['vector_cache_before']['warm_keys'])
   if trace:
    layers['domain']+=trace['domain_topics']-len(trace['existing_member_topics'])
    for label,key in [('sql32','scanned_topic_ids'),('valid_anchor32','qualified_topic_ids'),('metadata12','metadata_topic_ids')]:layers[label]+=len(trace[key])
   for key,allowed in q['expected_associations'].items():
    target=next(t['id'] for t in spec['topics'] if t['key']==key);loss=None
    if event is None:loss='not_started'
    elif target not in trace['scanned_topic_ids']:loss='domain_or_sql32'
    elif target not in trace['qualified_topic_ids']:loss='qualified_anchor32'
    elif target not in trace['metadata_topic_ids']:loss='metadata12'
    elif not any(p['article_id']==q['article_id'] and p['topic']==key for p in pairs):loss='vector4_or_execution'
    expected.append({'article_id':q['article_id'],'topic':key,'first_loss':loss})
  attempted=[p for p in pairs if any(b.task_id==p['judge_task_id'] for b in bs)]
  assoc=[p for p in attempted if p['associated']];applied=[p for p in pairs if p['applied']]
  negatives=[p for p in attempted if not p['association_expected']]
  metrics={'candidate_recall':ratio(sum(e['first_loss'] is None for e in expected),len(expected)),'raw_association_precision':ratio(sum(p['label_correct'] for p in assoc),len(assoc)),'all_first_label_accuracy':ratio(sum(p['label_correct'] for p in attempted),len(attempted)),'schema_valid':ratio(sum(p['schema_valid'] for p in attempted),len(attempted)),'strict_references':ratio(sum(p['reference_valid'] for p in attempted),len(attempted)),'label_compatible_final_coverage':ratio(sum(p['label_compatible_applied'] for p in applied),len(expected)),'strict_supported_final_coverage':'pending separate complete-basis review','different_topic_false_merges_among_applied':ratio(sum(not p['association_expected'] for p in applied),len(applied)),'wrong_relation_among_applied':ratio(sum(not p['label_compatible_applied'] for p in applied),len(applied)),'raw_false_associations_among_negatives':ratio(sum(p['associated'] for p in negatives),len(negatives)),'applied_among_attempted_negatives':ratio(sum(p['applied'] for p in negatives),len(negatives)),'all_invalid_applied':'pending separate complete-basis review','review_interception':'pending supportedness review of all actually reviewed decisions','real_reviewed_decisions':sum(p['real_audit_http_calls']>0 for p in pairs),'complete_review_bundles':sum(p['complete_bound_audit_protocol_pass'] for p in pairs),'rejected_review_decisions':sum(p['judgment_status']=='rejected' for p in pairs),'actual_cas_applied':len(applied),'stale_cas':sum(p['judgment_status']=='stale' for p in pairs)}
  costs={stage:{'physical_requests':sum(b.stage==stage for b in bs),'known_usd':str(sum((Decimal(str(usages[b.usage_id].cost_usd)) for b in bs if b.stage==stage and b.usage_id),Decimal(0))),'held_usd':str(sum((b.reserved_usd for b in bs if b.stage==stage and b.status in ['reserved','usage_unknown']),Decimal(0)))} for stage in ['topic_embedding','topic_judgment','topic_review']}
  audit_details=[]
  for b in bs:
   if b.stage!='topic_review':continue
   first_raw=raw(b);kind=bill_kinds.get(b.id);protocol=False;passed=False;error=None
   try:
    audit=MemberAudit.model_validate(first_raw)
    task=tasks[b.task_id];row=s.get(MemberJudgment,task.payload['decision_key']);dec=MemberDecision.model_validate(row.decision)
    expected_binding=review_binding(task.payload,dec)
    protocol=bool(audit.kind==kind and audit.binding==expected_binding and set(c.target for c in audit.checks)==set(audit_targets(dec,kind)) and len(audit.checks)==len(audit_targets(dec,kind)))
    passed=bool(protocol and audit_supported(audit,expected_binding,audit_targets(dec,kind)))
   except (ValidationError,ValueError,TypeError,KeyError) as e:error=str(e)
   audit_details.append({'request_id':b.id,'task_id':b.task_id,'article_id':b.article_id,'kind':kind,'first_output':first_raw,'protocol_valid':protocol,'supported_by_model':passed,'error':error,'known_usd':str(usages[b.usage_id].cost_usd) if b.usage_id else None})
  query_costs=[]
  completed=set(records[-1].get('completed_queries',[])) if records[-1]['event']=='complete' else set()
  for article,event in started.items():
   qb=[b for b in bs if b.article_id==article];qp=[p for p in pairs if p['article_id']==article]
   query_costs.append({'article_id':article,'query_run_finished':article in completed,'all_task_statuses':dict(Counter(t.status for t in ts if t.article_id==article)),'actual_embedding_http_calls':sum(b.stage=='topic_embedding' for b in qb),'actual_judgment_http_calls':sum(b.stage=='topic_judgment' for b in qb),'actual_audit_http_calls':sum(b.stage=='topic_review' for b in qb),'physical_requests':len(qb),'complete_query_known_usd':str(sum((Decimal(str(usages[b.usage_id].cost_usd)) for b in qb if b.usage_id),Decimal(0))),'active_held_usd':str(sum((b.reserved_usd for b in qb if b.status in ['reserved','usage_unknown']),Decimal(0))),'cache_state_before':{'unique_inputs':event['vector_cache_before']['unique_inputs'],'warm_versions':len(event['vector_cache_before']['warm_keys'])},'complete_four_audit_and_cas_pairs':[p['judgment_fingerprint'] for p in qp if p['applied'] and p['complete_bound_audit_protocol_pass']],'basis_success_pending_strict_review':True,'includes_all_selected_negative_judgments':True})
  phase_reports[phase]={'registration_id':worker,'registered_queries':len(spec['queries']),'started_queries':len(started),'expected_pairs':len(expected),'selected_pairs':len(pairs),'last_event':records[-1]['event'],'last_record':records[-1],'metrics':metrics,'layers':dict(layers),'pair_results':pairs,'expected_pair_losses':expected,'audit_details':audit_details,'costs':costs,'retries':len(bs)-len({(b.task_id,bill_kinds.get(b.id)) for b in bs if b.stage!='topic_embedding'})-sum(b.stage=='topic_embedding' for b in bs),'warm_lookup_occurrences':warm_occurrences,'distinct_warm_versions':len(warm_union),'all_first_outputs_preserved':True,'complete_query_costs':query_costs}
 # Challenges remain a separate population and never contribute to natural precision/coverage.
 challenge_path=OUT/'challenge-first-run.ndjson';challenge_records=[json.loads(line) for line in challenge_path.read_text().splitlines()] if challenge_path.exists() else []
 challenge_spec=json.loads((ROOT/exe['challenge_registration']['path']).read_text());challenge_cases=[]
 for case in challenge_spec['cases']:
  injected=next((r for r in challenge_records if r['event']=='injected_challenge' and r['case']['id']==case['id']),None)
  task=tasks.get(injected['task_id']) if injected else None;row=judgments.get(task.id) if task else None
  calls=[b for b in bills if row and b.task_id in [t.id for t in tasks.values() if t.kind=='topic_review' and t.payload.get('decision_key')==row.input_fingerprint]]
  challenge_cases.append({'id':case['id'],'expected':case['expected_status'],'article_id':case['article_id'],'judge_task_id':task.id if task else None,'judge_status':task.status if task else None,'judgment_fingerprint':row.input_fingerprint if row else None,'actual_status':row.status if row else (task.status if task else None),'review':row.review if row else None,'audit_http_calls':len(calls),'audit_kinds':[bill_kinds.get(b.id) for b in calls],'known_usd':str(sum((Decimal(str(usages[b.usage_id].cost_usd)) for b in calls if b.usage_id),Decimal(0))),'pre_llm_case':bool(case.get('pre_llm_failure')),'replayed_real_audit':bool(case.get('replay_actual_review_from')),'natural_end_to_end':False})
 challenge_bills=[b for b in bills if attempts[b.task_attempt_id].worker==challenge_spec['id']]
 challenge_audit_details=[]
 for b in challenge_bills:
  first_raw=raw(b);kind=bill_kinds.get(b.id);protocol=False;passed=False;error=None
  try:
   audit=MemberAudit.model_validate(first_raw)
   task=tasks[b.task_id];row=s.get(MemberJudgment,task.payload['decision_key']);dec=MemberDecision.model_validate(row.decision)
   binding=review_binding(task.payload,dec)
   protocol=bool(audit.kind==kind and audit.binding==binding and set(c.target for c in audit.checks)==set(audit_targets(dec,kind)) and len(audit.checks)==len(audit_targets(dec,kind)))
   passed=bool(protocol and audit_supported(audit,binding,audit_targets(dec,kind)))
  except (ValidationError,ValueError,TypeError,KeyError) as e:error=str(e)
  challenge_audit_details.append({'request_id':b.id,'task_id':b.task_id,'article_id':b.article_id,'kind':kind,'first_output':first_raw,'protocol_valid':protocol,'supported_by_model':passed,'error':error,'known_usd':str(usages[b.usage_id].cost_usd) if b.usage_id else None})
 state=batch_state(s);fees=sum((Decimal(str(usages[b.usage_id].cost_usd)) for b in bills if b.usage_id),Decimal(0))
 prefix=Decimal('0.03171912');peak=prefix
 for b in bills:
  peak=max(peak,prefix+b.reserved_usd)
  if b.usage_id:prefix+=Decimal(str(usages[b.usage_id].cost_usd))
 holds=[dict(r) for r in s.execute(text("SELECT id,status,reserved_usd::text,provider_generation_id FROM billed_requests WHERE status IN ('reserved','usage_unknown') ORDER BY id")).mappings()]
 old_ids={r['id'] for r in exe['original_holds']};assert [r for r in holds if r['id'] in old_ids]==exe['original_holds']
 assert peak<=Decimal('0.30') and state['physical_requests']==107+len(bills)
 result={'schema_version':'r206-grounding-initial-report-v1','at':datetime.now(UTC).isoformat(),'source_freeze_sha256':hashlib.sha256(FREEZE.read_bytes()).hexdigest(),'execution_fingerprint':fingerprint(exe),'phases':phase_reports,'separate_challenges':{'cases':challenge_cases,'last_event':challenge_records[-1]['event'] if challenge_records else None,'real_physical_requests':len(challenge_bills),'known_usd':str(sum((Decimal(str(usages[b.usage_id].cost_usd)) for b in challenge_bills if b.usage_id),Decimal(0))),'actual_cas_event':next((r for r in challenge_records if r['event']=='actual_cas_competition'),None),'not_natural_quality':True,'audit_details':challenge_audit_details},'new_physical_requests':len(bills),'new_known_usd':str(fees),'cumulative_r206_known_usd':str(Decimal('0.03171912')+fees),'cumulative_r206_requests':state['physical_requests'],'peak_known_plus_full_reservation_usd':str(peak),'same_pool_cap_usd':'0.30','original_seven_holds_unchanged':True,'old_held_usd':'0.484867','new_unresolved_holds':[r for r in holds if r['id'] not in old_ids],'request_reconstruction_failures':reconstruction_failures,'every_reconstructed_payload_matches_original_hash':not reconstruction_failures,'old_task76_and_task110_retained':True,'strict_basis_review_pending':True,'fresh_blind_prepared':(ROOT/exe['new_blind_seal']).exists(),'first_output_hashes':{phase:hashlib.sha256((OUT/(phase+'-first-run.ndjson')).read_bytes()).hexdigest() for phase in ['exposed','challenge','blind'] if (OUT/(phase+'-first-run.ndjson')).exists()},'source_or_parameter_tuning_after_first_output':False,'user_acceptance':None,'production_enabled':False}
 write('results-initial.json',result)
 export('physical-requests.json.gz',[dict(s.execute(select(BilledRequest.__table__).where(BilledRequest.id==b.id)).mappings().one())|{'known_paid_usd':str(usages[b.usage_id].cost_usd) if b.usage_id else None,'reconstructed_kind':bill_kinds.get(b.id)} for b in bills])
 export('reconstructed-requests.json.gz',reconstruction)
 ids=[t.id for t in tasks.values() if t.strategy_version==member_contract()['version']]
 export('tasks.json.gz',[dict(r) for r in s.execute(select(PipelineTask.__table__).where(PipelineTask.id.in_(ids))).mappings()])
 export('attempts.json.gz',[dict(r) for r in s.execute(select(TaskAttempt.__table__).where(TaskAttempt.task_id.in_(ids))).mappings()])
 export('judgments.json.gz',[dict(r) for r in s.execute(select(MemberJudgment.__table__).where(MemberJudgment.task_id.in_(ids))).mappings()])
 export('vectors.json.gz',[dict(r) for r in s.execute(select(ContentVector.__table__)).mappings()])
 print(json.dumps({'new_known_usd':str(fees),'new_requests':len(bills),'metrics':{p:r.get('metrics') for p,r in phase_reports.items()},'challenge_statuses':{c['id']:c['actual_status'] for c in challenge_cases},'reconstruction_failures':reconstruction_failures},indent=2))
