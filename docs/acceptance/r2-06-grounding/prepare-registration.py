"""Freeze exposed historical cases and the authorized same-pool budget revision; no paid calls."""
import gzip,hashlib,json
from datetime import UTC,datetime
from pathlib import Path
from uuid import NAMESPACE_URL,uuid5
from unspun.core.member_contracts import member_contract
from unspun.evaluation.member_quality import registration
ROOT=Path(__file__).resolve().parents[3];OUT=Path(__file__).parent;REG=ROOT/'docs/evaluations/r2'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(path,value):
 with path.open('x') as f:json.dump(value,f,ensure_ascii=False,indent=2)
old=registration(require_current_contract=False)
previous=json.loads((REG/'member-retest-v1.json').read_text())
seal=json.loads((REG/'member-blind-seal-v2.json').read_text());private=Path(seal['sealed_directory'])
for row in seal['files']:assert sha(private/row['path'])==row['sha256']
blind=json.loads((private/'registration.json').read_text());seed_refs=json.loads((private/'seed-references-v1.json').read_text())
exposed_inputs=REG/'member-grounding-exposed-inputs-v1.json.gz'
with exposed_inputs.open('xb') as raw:
 with gzip.GzipFile(fileobj=raw,mode='wb',mtime=0) as f:f.write((private/'inputs.json').read_bytes())
topics=[];queries=[]
for phase,spec in [('original',old),('previously_blind',blind)]:
 for topic in spec['topics']:
  t=dict(topic);t['original_id']=t['id'];t['original_split']=t['split'];t['split']='exposed_validation'
  t['id']=str(uuid5(NAMESPACE_URL,'r206-grounding-v1:exposed:'+t['key']))
  t['seed_reference']=previous['regression']['seed_references'][t['key']] if phase=='original' else seed_refs[t['original_id']]
  topics.append(t)
 for query in spec['queries']:
  q=dict(query);q['original_split']=q['split'];q['split']='exposed_validation';q['exposure_origin']=phase;queries.append(q)
value={'schema_version':'r206-grounding-exposed-v1','id':'r206-grounding-v1:exposed','at':datetime.now(UTC).isoformat(),'base_revision':'4f275b9d236acc315c49a735c6527b43ffc7cde9','topics':topics,'queries':queries,'unavailable_inputs':old['unavailable_inputs'],'counts':{'registered_queries':18,'executable_queries':17,'topics':16,'expected_pairs':9,'previously_blind_queries_now_exposed':6},'original_freezes_labels_first_outputs_unchanged':True,'reuse_requires_exact_original_package_and_current_input':True,'input_sources':[{'path':'docs/evaluations/r2/member-inputs-v1.json','sha256':sha(REG/'member-inputs-v1.json'),'material_offset':100000},{'path':str(exposed_inputs.relative_to(ROOT)),'sha256':sha(exposed_inputs),'material_offset':200000}],'technical_gates':old['technical_gates'],'user_acceptance':None,'production_enabled':False}
write(REG/'member-grounding-exposed-v1.json',value)
budget={'schema_version':'r206-grounding-budget-v1','id':'r206-grounding-v1','at':datetime.now(UTC).isoformat(),'authorized_by':'User explicitly raised the SAME cumulative R2-06 pool from 0.20 to 0.30 for grounding hardening and validation; no automatic extension.','contract':member_contract(),'exposed_registration':{'path':'docs/evaluations/r2/member-grounding-exposed-v1.json','sha256':sha(REG/'member-grounding-exposed-v1.json')},'original_holds':previous['original_holds'],'budget':{'batch_limit_usd':'0.30','previous_spend_usd':'0.03171912','previous_physical_requests':107,'previous_stage_counts':{'topic_embedding':22,'topic_judgment':82,'topic_review':3},'future_reserved_usd':'0','maximum_new_known_plus_active_reservation_usd':'0.26828088','physical_request_limit':360,'stage_physical_limits':{'topic_embedding':80,'topic_judgment':184,'topic_review':96},'previous_stage_caps_usd':{'topic_embedding':'0.02','topic_judgment':'0.08','topic_review':'0.20'},'stage_caps_usd':{'topic_embedding':'0.02','topic_judgment':'0.13','topic_review':'0.30'},'stage_ceilings_are_overlapping_not_separate_allocations':True,'original_evaluation_limit_usd':'1.50','original_unknown_holds_usd':'0.484867','full_reservation_algorithm_unchanged':True,'grounding_budget_24h_usd':'1.00','production_grounding_budget_unchanged':'0.40','retry_policy':'No task execution retry; existing at most one length-truncation physical retry counts in every cap.','stop_policy':'Any new unknown/active unresolved cost or reached monetary/physical limit stops ALL paid phases immediately. No release/reset/automatic increase.'},'phases':{'challenge':{'physical_request_limit':36,'cumulative_pool_ceiling_usd':'0.30'},'exposed':{'physical_request_limit':124,'cumulative_pool_ceiling_usd':'0.30'},'blind':{'physical_request_limit':93,'cumulative_pool_ceiling_usd':'0.30'}},'new_physical_requests_at_most':253,'new_blind_seal':'docs/evaluations/r2/member-grounding-blind-seal-v1.json','new_blind_preparation_requires':'Completed isolated regression, real challenges and exposed numeric gates 90%/95%/80%, zero invalid writes, plus complete basis review. Failure means NO fresh blind preparation or paid run.','new_blind_registration_is_append_only_after_gate_and_reviewed_before_pay':True,'original_unfinished_task_110_preserved_not_resumed':True,'production_enabled':False,'user_acceptance':None}
write(REG/'member-grounding-budget-v1.json',budget)
print(json.dumps({'exposed':value['counts'],'pool':budget['budget'],'new_paid_requests':0},indent=2))
