"""Separate delivery/accounting integrity from the failed real-model technical gates."""
import hashlib
import json
import subprocess
from datetime import UTC,datetime
from decimal import Decimal
from pathlib import Path
OUT=Path(__file__).parent
ROOT=OUT.parents[2]
def read(name):return json.loads((OUT/name).read_text())
pre={k:read('predeploy-'+k+'.json') for k in ('runtime','reading','production','evaluation','retained','protected-production','observation','member-chain')}
post={k:read('postdeploy-'+k+'.json') for k in pre}
audit=read('postdeploy-audit.json');schema=read('postdeploy-schema.json');result=read('results-v1.json');fee=read('fee-reconciliation.json');recovery=read('official-restore.json')
revision='1abcadf606a05fc7db4d4873aaaa251503f39268';evaluation='2d8daf37aa0284fa7387bd4a275c628cecc36d69'
checks={}
checks['actual_runtime_health_and_schema']=post['runtime']['health']['version']==revision and schema['schema']=='000019' and schema['migration_heads']==['000019']
actual=post['runtime']['api_metadata']['source_sha256']
expected={k:hashlib.sha256(subprocess.check_output(['git','show',revision+':server/src/unspun/'+k],cwd=ROOT)).hexdigest() for k in actual}
checks['all_90_deployed_sources_match_actual_release']=len(actual)==90 and actual==expected
local=read('import-check-final.json')['source_sha256']
diff=[k for k in actual if actual[k]!=local[k]]
checks['only_standalone_evaluation_tool_differs_from_local_main']=diff==['evaluation/member_quality.py']
checks['config_sources_models_r1_contracts_unchanged']=pre['runtime']['api_metadata']['config_sha256']==post['runtime']['api_metadata']['config_sha256'] and all(pre['production'][k]==post['production'][k] for k in ('sources','models','contracts'))
checks['seven_production_tables_empty']=len(schema['tables'])==7 and all(t['rows']==0 for t in schema['tables'].values())
m=post['member-chain'];checks['production_member_chain_off_and_empty']=m['configured_member_processing_enabled'] is False and m['runtime']['member_processing_enabled'] is False and not m['member_handlers'] and not m['topic_tasks'] and not m['topic_calls']
checks['production_allocation_unchanged_no_topic_caps']=m['policy']==pre['member-chain']['policy'] and all(Decimal(str(m['policy']['stage_caps'].get(k,0)))==0 for k in ('topic_embedding','topic_judgment','topic_review'))
a=next(c for c in audit['containers'] if c['service']=='api');w=next(c for c in audit['containers'] if c['service']=='r1-worker')
checks['fixed_api_worker_same_release']=a['image']==w['image']=='ghcr.io/linsrock/unspun-server:'+revision and a['image_id']==w['image_id'] and a['app_version']==w['app_version']==revision
checks['no_api_worker_observer_mounts']=a['mounts']==w['mounts']==[]
checks['legacy_zero_controlled_one']=audit['legacy_all_states']==0 and audit['controlled_running']==1 and 'worker' not in audit['services']
checks['only_8080_loopback_published']=[(c['service'],c['ports']) for c in audit['containers'] if c['ports']]==[('web',{'80/tcp':[{'HostIp':'127.0.0.1','HostPort':'8080'}]})]
checks['web_image_unchanged']=next(c['image'] for c in pre['runtime']['running_containers'] if c['name']=='unspun-web-1')==next(c['image'] for c in post['runtime']['running_containers'] if c['name']=='unspun-web-1')
old_details={r['id']:r for r in pre['reading']['qualified_details_verified']};new_details={r['id']:r for r in post['reading']['qualified_details_verified']}
checks['original_117_details_preserved']=len(old_details)==117 and all(new_details.get(k)==v for k,v in old_details.items())
added=set(new_details)-set(old_details);natural=read('production-window-after-paid.json')
checks['all_four_reading_additions_are_original_r1_natural']=added=={8941,8965,9126,9165} and added.issubset({r['article_id'] for r in natural['concurrent_requests']})
checks['reading_is_readonly_no_paid_enqueue']=all(v['tasks_before']==v['tasks_after'] and v['paid_requests']==v['database_writes']==0 for v in (pre['reading'],post['reading']))
checks['new_sources_closed_no_publications']=pre['reading']['new_path_published']==post['reading']['new_path_published']==0 and all(not any(s['r1'][k] for k in ('discovery','material','paid','publish')) and s['r1']['paid_scopes']==s['r1']['publish_scopes']==[] for s in post['production']['sources'] if s['id'] in ('thepaper-sidebar','36kr-newsflashes'))
checks['events_reader_feedback_preserved']=all(pre['retained']['tables'][k]==post['retained']['tables'][k] for k in ('events','reader_state','reader_interests','content_feedback','reader_changes'))
checks['old_identity_rows_preserved_with_natural_append']=all(t['original_prefix_matches'] for t in read('production-identity-check.json')['tables'].values())
checks['legacy_business_backlog_policy_preserved']=all(pre['protected-production']['queries'][k]==post['protected-production']['queries'][k] for k in ('legacy_articles','legacy_summary_pending','legacy_summary_abandoned','legacy_runs','digests','source_ownership','policy','unknown'))
checks['r204_containers_and_original_183_files_preserved']=pre['observation']['containers']==post['observation']['containers'] and len(pre['observation']['retained_files'])==183 and all(post['observation']['retained_files'].get(k)==v for k,v in pre['observation']['retained_files'].items())
checks['r204_worktree_preserved']=read('protected-r204-worktree-final.json')['source_and_config_unchanged'] and read('protected-r204-worktree-final.json')['status']==''
checks['original_eval_seven_holds_and_carry_preserved']=pre['evaluation']['unknown_requests']==post['evaluation']['unknown_requests'] and len(post['evaluation']['unknown_requests'])==7 and pre['evaluation']['carry']==post['evaluation']['carry']
checks['official_complete_restore_and_old_rows_preserved']=recovery['all_rows_counts_hashes_sequences_match'] and all(t['preserved'] for t in recovery['original_old_rows']) and recovery['original_policy']['only_stage_caps_changed']
checks['independent_provider_fee_and_budget_audit_passed']=fee['all_independent_assertions_passed'] and fee['provider_delta_matches_natural_production_plus_this_batch'] and Decimal(fee['known_new_usd'])==Decimal('0.01213610') and Decimal(fee['new_held_usd'])==0
checks['raw_first_results_preserved_no_tuning']=result['first_run_sha256']==hashlib.sha256((OUT/'first-run.ndjson').read_bytes()).hexdigest()==fee['first_run_sha256'] and result['tuning_after_first_output'] is False
checks['all_selected_candidates_counted']=result['metrics']['selected_candidate_pairs']==result['metrics']['judge_attempted_pairs']==40 and result['metrics']['judgment_precision']['denominator']==8
main=read('preparation-main-ci.json');job=next(j for j in main['jobs'] if j['name']=='deploy')
checks['actual_deploy_step_executed']=main['conclusion']=='success' and job['conclusion']=='success' and any(s['name']=='Deploy' and s['conclusion']=='success' for s in job['steps'])
identity=read('identity-main-ci.json')
checks['evaluation_only_main_correctly_skipped_runtime_deploy']=identity['headSha']==evaluation and identity['conclusion']=='success' and all(next(j for j in identity['jobs'] if j['name']==n)['conclusion']=='skipped' for n in ('build-push','deploy'))
checks['failed_quality_and_unmeasured_review_are_explicit']=result['overall_technical_pass'] is False and result['metrics']['final_member_coverage']['numerator']==0 and result['metrics']['review_rejection']['denominator']==0
out={'at':datetime.now(UTC).isoformat(),'runtime_revision':revision,'evaluated_main_revision':evaluation,'standalone_tool_difference':diff,'engineering_accounting_retention_checks':checks,'all_delivery_checks_passed':all(checks.values()),'real_model_technical_gates':result['technical_gates'],'real_model_technical_pass':False,'review_and_cas_real_quality':'unmeasured; zero reached','r206_complete':False,'production_member_processing_enabled':False,'r204_continuation_accepted_by_this_batch':False}
with (OUT/'delivery.json').open('x') as f:json.dump(out,f,indent=2)
print(json.dumps(out,indent=2));assert all(checks.values())
