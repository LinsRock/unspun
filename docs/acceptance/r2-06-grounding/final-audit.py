"""Read-only evidence invariants for the stopped run and protected production."""
import gzip,hashlib,json,subprocess
from datetime import UTC,datetime
from decimal import Decimal
from pathlib import Path
from unspun.evaluation.member_grounding import load_execution,FREEZE
OUT=Path(__file__).parent;ROOT=OUT.parents[2]
def read(n):return json.loads((OUT/(n+'.json')).read_text())
exe=load_execution();report=read('results-final');initial=read('results-initial');fees=read('fee-reconciliation')
assert report['all_new_paid_work_stopped'] and report['user_acceptance'] is None
assert initial['source_freeze_sha256']==hashlib.sha256(FREEZE.read_bytes()).hexdigest()
for phase,digest in report['first_output_hashes'].items():assert hashlib.sha256((OUT/(phase+'-first-run.ndjson')).read_bytes()).hexdigest()==digest
requests=json.loads(gzip.decompress((OUT/'physical-requests.json.gz').read_bytes()));reconstructed=json.loads(gzip.decompress((OUT/'reconstructed-requests.json.gz').read_bytes()))
assert len(requests)==len(reconstructed)==32
assert len({r['id'] for r in requests})==32 and len({(r['task_id'],r['reconstructed_kind']) for r in requests})==32
assert sum(Decimal(r['known_paid_usd']) for r in requests if r['known_paid_usd'] is not None)==Decimal('0.04562381')
assert sum(r['status']=='usage_unknown' for r in requests)==1
for request in reconstructed:
 if request['kind']=='query_support':
  packet=json.loads(request['request']['messages'][1]['content'])
  assert {m['role'] for m in packet['materials']}=={'query'} and set(packet).isdisjoint({'candidate','query','decision','complete_basis'})
  assert all(m['content']['article_id']==next(r['article_id'] for r in requests if r['id']==request['request_id']) for m in packet['materials'])
assert fees['phase_paid_attempts']=={'challenge':13,'exposed':19,'blind':0} and fees['paid_retries']==0
assert Decimal(fees['same_pool_cumulative_known_usd'])+Decimal(fees['same_pool_active_full_holds_usd'])<=Decimal('0.30')
assert fees['provider_minus_known_new_and_r1_residual_usd']=='0E-8' or Decimal(fees['provider_minus_known_new_and_r1_residual_usd'])==0
recovery=read('after-recovery');assert recovery['all_table_counts_hashes_sequences_match']
assert all(r['all_original_rows_unchanged'] or (r['table']=='budget_policy' and r['authorized_registered_stage_caps_only']) for r in recovery['retained_original_rows'])
chain=read('final-member-chain');runtime=read('final-runtime');old_runtime=read('postdeploy-runtime');bound=read('final-boundaries')
assert runtime['health']['version']=='beb8e03ade1bfac90ffd509eb340f35210494275'
assert runtime['api_metadata']['source_sha256']==old_runtime['api_metadata']['source_sha256']
assert runtime['api_metadata']['config_sha256']==old_runtime['api_metadata']['config_sha256']
assert chain['schema']=='000019' and not chain['configured_member_processing_enabled'] and not chain['runtime']['member_processing_enabled']
assert chain['member_handlers']==chain['topic_tasks']==chain['topic_calls']==[] and all(t['rows']==0 for t in chain['tables'].values()) and len(chain['tables'])==7
assert all(k not in chain['policy']['stage_caps'] for k in ['topic_embedding','topic_judgment','topic_review'])
before,after=read('predeploy-observation'),read('final-observation');assert before['containers']==after['containers']
assert all(after['retained_files'].get(k)==v for k,v in before['retained_files'].items())
assert not (ROOT/exe['new_blind_seal']).exists() and not (OUT/'blind-first-run.ndjson').exists()
assert read('final-freeze-check')['failed_gate_probe']['paid_request_count_unchanged']
report={'at':datetime.now(UTC).isoformat(),'evidence_review':'primary-agent independent recomputation against immutable evidence; not a new blind reviewer','frozen_files':109,'physical_requests_exported_and_reconstructed':32,'all_request_hashes_and_full_reservations_matched':initial['every_reconstructed_payload_matches_original_hash'],'all_query_only_audit_requests_contain_only_query_originals':True,'paid_retries':0,'provider_fee_residual_usd':'0','unknown_hold_kept':'0.029746','all_eight_holds_kept':'0.514613','only_authorized_original_budget_stage_caps_changed':True,'original_task76_and_task110_rows_preserved':True,'restored_all_tables_counts_hashes_sequences_match':True,'production_revision':runtime['health']['version'],'production_source_files_unchanged_from_actual_deployment':len(runtime['api_metadata']['source_sha256']),'production_member_enabled':False,'production_member_tasks':0,'production_member_calls':0,'empty_member_chain_tables':7,'production_new_stage_allocations':0,'protected_r204_containers':len(before['containers']),'protected_r204_original_files':len(before['retained_files']),'r204_old_file_hashes_and_container_identities_unchanged':True,'new_blind_prepared_or_read':False,'negative_blind_gate_verified':True,'user_acceptance':None,'findings':'Real validation failed. Schema-length and audit fingerprint copying fail, and semantic sub-audit misses remain. Zero natural writes does not establish successful precision or coverage.'}
with (OUT/'final-audit.json').open('x') as f:json.dump(report,f,indent=2)
print(json.dumps(report,indent=2))
