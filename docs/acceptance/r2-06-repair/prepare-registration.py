"""Register only exposed regression/challenges and the redacted independent holdout seal."""
import json
from datetime import UTC,datetime
from pathlib import Path
from uuid import NAMESPACE_URL,uuid5
from sqlalchemy import create_engine,text
from sqlalchemy.orm import Session
from unspun.core.member_contracts import member_contract,MemberDecision
from unspun.core.member_recall import current_input
from unspun.core.sources import load_sources
from unspun.evaluation.member_quality import registration
ROOT=Path(__file__).resolve().parents[3]
OUT=ROOT/'docs/evaluations/r2/member-retest-v1.json'
if (ROOT/'docs/evaluations/r2/member-repair-freeze-v1.json').exists():
 raise ValueError('registration is frozen; never overwrite it')
old=registration(require_current_contract=False)
engine=create_engine('postgresql+psycopg://unspun:unspun@localhost:5432/unspun_quality_r1_20261016')
cases=[];topics=[];seed_references={}
voices={"france":"description","huang":"reported","canada":"reported","mercenary":"reported","westbank":"description","hongkong":"author","uzbekistan":"reported","tajikistan":"reported","deepseek":"reported","japan-era":"author"}
plans=[('date-conflict',8905,'canada','same_event',False,False,'The September 17 date must be a typo because feed dates align with October 17.','reported'),('anchor-contamination',8926,'japan-era','explanation',False,False,'The query explains the Japanese era naming system and its regional history.','reported'),('analysis-as-report',8899,'huang','same_event',False,False,'The query is a factual report of the announcement launching this investigation.','author'),('correct-apply',8881,'france','same_event',True,False,'The query reports the same nationwide French protests and riots as the anchor.','reported'),('correct-stale',8898,'france','same_event',True,True,'The query reports the same nationwide French protests and riots as the anchor.','reported')]
with Session(engine) as session:
 session.execute(text('SET TRANSACTION READ ONLY'))
 holds=[dict(r) for r in session.execute(text("SELECT id,status,reserved_usd::text,provider_generation_id FROM billed_requests WHERE status IN ('reserved','usage_unknown') ORDER BY id")).mappings()]
 assert len(holds)==7
 for t in old["topics"]:
  c=current_input(session,t["anchors"][0],load_sources(),datetime.now(UTC))["content"]
  seed_references[t["key"]]={"paragraph":0,"quote":c["paragraphs"][0]["text"][:400],"voice":voices[t["key"]]}
 for key,article,topic_key,label,approve,race,basis,voice in plans:
  topic=next(t for t in old['topics'] if t['key']==topic_key)
  identity=str(uuid5(NAMESPACE_URL,'r206-retest-v1:challenge:'+key))
  topics.append({**topic,'seed_reference':seed_references[topic_key],'key':key,'id':identity,'split':'review_challenge'})
  query=current_input(session,article,load_sources(),datetime.now(UTC))
  anchor=current_input(session,topic['anchors'][0],load_sources(),datetime.now(UTC))
  refs=[]
  for snap,v in [(query,voice),(anchor,'reported')]:
   content=snap['content'];scope=content['scope']
   v={'question_background':'question','media_description':'description'}.get(scope,v)
   refs.append({'article_id':content['article_id'],'material_id':content['material_id'],'paragraph':0,'quote':content['paragraphs'][0]['text'][:400],'voice':v})
  decision=MemberDecision(classification=label,certainty='certain',basis=basis,evidence=refs).model_dump(mode='json')
  cases.append({'id':key,'article_id':article,'topic_id':identity,'decision':decision,'expected_review_approval':approve,'force_revision_after_review':race,'expected_final_status':'stale' if race else 'applied' if approve else 'rejected','judgment_origin':'explicit manually authored reviewer challenge; no model judgment and excluded from natural quality'})
value={'schema_version':'r206-retest-execution-v1','id':'r206-retest-v1','registered_at':datetime.now(UTC).isoformat(),'base_revision':'7edad005ff7579a0e6c8a2e40e3d92db2374b26c','database':'unspun_quality_r1_20261016','contract':member_contract(),'blind_seal':'docs/evaluations/r2/member-blind-seal-v2.json','original_holds':holds,'budget':{'batch_limit_usd':'0.20','previous_spend_usd':'0.01213610','previous_physical_requests':59,'future_reserved_usd':'0','maximum_new_spend_usd':'0.18786390','physical_request_limit':180,'stage_physical_limits':{'topic_embedding':48,'topic_judgment':112,'topic_review':20},'stage_caps_usd':{'topic_embedding':'0.02','topic_judgment':'0.08','topic_review':'0.20'},'limits_are_cumulative_with_previous_r206':True,'future_reservations':'Each upcoming physical call retains the original full-output-window reservation_bound, including reasoning. No discretionary future-credit reservation was created. The unfrozen 0.03 planning draft was corrected before source freeze or any paid call; all seven original holds are unchanged.','unknown_policy':'Any new pending/unknown or reached money/request cap stops all further paid requests; reconcile without retry or releasing old holds.','physical_retry_policy':'Unchanged client: at most one retry with doubled completion tokens for an unparseable length-truncated response; both physical calls count. No task execution retry.','grounding_budget_24h_usd':'1.00','production_grounding_budget_unchanged':'0.40'},'phases':{'regression':{'physical_request_limit':60,'cumulative_pool_ceiling_usd':'0.20'},'blind':{'physical_request_limit':55,'cumulative_pool_ceiling_usd':'0.20'},'challenge':{'physical_request_limit':6,'cumulative_pool_ceiling_usd':'0.20'}},'regression':{'seed_references':seed_references,'registered_queries':12,'executable_queries':11,'unavailable_queries':1,'expected_pairs':6,'prior_holdout_role':'exposed regression only in this version; original frozen split and scores unchanged','topics':'New UUID namespace, genuine same frozen anchors; recall scope is the complete registered pool, never the expected positive subset. Existing evaluation objects remain unchanged.'},'blindness':{'reviewer':'one independent read-only subagent','root_has_opened_materials_or_labels':False,'release_rule':'Reviewed entry consumes seal only after exact frozen source/contract and DB-verified complete old regression. Root opens materials/labels for reporting only after all natural first outputs finish or a guard stops the first run. No tuning after first real output.'},'technical_gates':old['technical_gates'],'metrics':old['metrics'],'challenges':{'id':'r206-retest-v1:challenge','topics':topics,'queries':[{'article_id':c['article_id'],'split':'review_challenge'} for c in cases],'cases':cases,'natural_end_to_end':False},'user_acceptance':None,'production_enabled':False,'r204_status_from_user':{'window_finished':True,'36kr_successful_rounds':21,'36kr_total_rounds':21,'36kr_material_review':'pending','thepaper_successful_rounds':18,'thepaper_total_rounds':21,'thepaper_90_percent_gate':False,'both_routes_enabled':False,'full_window_review':'separate batch'}}
with OUT.open('w') as f:json.dump(value,f,indent=2,ensure_ascii=False)
print('Registered cumulative pool and request limits, 12 exposed queries, sealed holdout, and 5 separate reviewer challenges; 0 writes/paid calls')
