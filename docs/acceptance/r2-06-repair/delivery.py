"""Read-only delivery integrity, separate from real-model quality and guard stops."""
import hashlib,json
from datetime import UTC,datetime
from decimal import Decimal
from pathlib import Path
OUT=Path(__file__).parent;ROOT=OUT.parents[2]
def read(name):return json.loads((OUT/name).read_text())
revision=read('preparation-merged.json')['mergeCommit']['oid']
pre={k:read('predeploy-'+k+'.json') for k in ['runtime','reading','production','evaluation','retained','protected-production','observation','member-chain']}
post={k:read('postdeploy-'+k+'.json') for k in pre}
final=read('final-member-chain.json');audit=read('postdeploy-audit.json');schema=read('postdeploy-schema.json');ci=read('preparation-main-ci.json');recovery=read('after-recovery.json');fee=read('fee-reconciliation.json');result=read('results-v2.json')
actual=post['runtime']['api_metadata']['source_sha256'];expected={str(p.relative_to(ROOT/'server/src/unspun')):hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'server/src/unspun').rglob('*.py')}
checks={}
checks['health_schema_source_release_match']=post['runtime']['health']['version']==revision and schema['schema']=='000019' and schema['migration_heads']==['000019'] and actual==expected
checks['all_92_deployed_sources_match']=len(actual)==92 and actual==expected
checks['actual_deploy_step_succeeded']=ci['conclusion']=='success' and any(j['name']=='deploy' and j['conclusion']=='success' and any(s['name']=='Deploy' and s['conclusion']=='success' for s in j['steps']) for j in ci['jobs'])
checks['production_off_before_after_and_final']=all(m['configured_member_processing_enabled'] is False and not m['member_handlers'] and not m['topic_tasks'] and not m['topic_calls'] and m['runtime']['member_processing_enabled'] is False for m in [pre['member-chain'],post['member-chain'],final])
checks['seven_new_production_tables_still_empty']=len(final['tables'])==7 and all(t['rows']==0 for t in final['tables'].values())
checks['production_policy_no_new_allocations']=final['policy']==pre['member-chain']['policy'] and all(Decimal(str(final['policy']['stage_caps'].get(k,0)))==0 for k in ['topic_embedding','topic_judgment','topic_review'])
checks['original_sources_models_card_contract_and_configs_unchanged']=pre['runtime']['api_metadata']['config_sha256']==post['runtime']['api_metadata']['config_sha256'] and all(pre['production'][k]==post['production'][k] for k in ['sources','models','contracts'])
a=next(c for c in audit['containers'] if c['service']=='api');w=next(c for c in audit['containers'] if c['service']=='r1-worker')
checks['api_and_controlled_worker_fixed_same_release']=a['image']==w['image']=='ghcr.io/linsrock/unspun-server:'+revision and a['image_id']==w['image_id'] and a['app_version']==w['app_version']==revision
checks['no_runtime_source_mounts']=a['mounts']==w['mounts']==[]
checks['legacy_zero_controlled_one']=audit['legacy_all_states']==0 and audit['controlled_running']==1 and 'worker' not in audit['services']
checks['only_8080_loopback_published']=[(c['service'],c['ports']) for c in audit['containers'] if c['ports']]==[('web',{'80/tcp':[{'HostIp':'127.0.0.1','HostPort':'8080'}]})]
checks['web_immutable_reference_reused']=next(c['image'] for c in pre['runtime']['running_containers'] if c['name']=='unspun-web-1')==next(c['image'] for c in post['runtime']['running_containers'] if c['name']=='unspun-web-1')
old={r['id']:r for r in pre['reading']['qualified_details_verified']};new={r['id']:r for r in post['reading']['qualified_details_verified']}
checks['original_readable_details_and_bodies_preserved']=all(new.get(k)==v for k,v in old.items())
checks['reading_no_enqueue_or_paid_calls']=all(v['tasks_before']==v['tasks_after'] and v['paid_requests']==v['database_writes']==0 for v in [pre['reading'],post['reading']])
checks['r204_sources_closed_no_publications']=pre['reading']['new_path_published']==post['reading']['new_path_published']==0 and all(not any(s['r1'][k] for k in ['discovery','material','paid','publish']) and s['r1']['paid_scopes']==s['r1']['publish_scopes']==[] for s in post['production']['sources'] if s['id'] in ['thepaper-sidebar','36kr-newsflashes'])
checks['events_feedback_reader_state_preserved']=all(pre['retained']['tables'][k]==post['retained']['tables'][k] for k in ['events','reader_state','reader_interests','content_feedback','reader_changes'])
checks['original_identity_rows_preserved']=all(t['original_prefix_matches'] for t in read('production-identity-check.json')['tables'].values())
checks['legacy_business_and_backlog_preserved']=all(pre['protected-production']['queries'][k]==post['protected-production']['queries'][k] for k in ['legacy_articles','legacy_summary_pending','legacy_summary_abandoned','legacy_runs','digests','source_ownership','policy','unknown'])
checks['r204_containers_mounts_and_all_old_files_unchanged']=pre['observation']['containers']==post['observation']['containers'] and all(post['observation']['retained_files'].get(k)==v for k,v in pre['observation']['retained_files'].items())
checks['original_cumulative_rows_and_policy_preserved']=recovery['all_table_counts_hashes_sequences_match'] and all(r['all_original_rows_unchanged'] for r in recovery['retained_original_rows'])
checks['old_seven_holds_and_pool_preserved']=fee['original_seven_holds_unchanged'] and Decimal(fee['peak_known_plus_complete_next_reservation_usd'])<=Decimal('0.20') and Decimal(fee['cumulative_r206_known_usd'])<=Decimal('0.20')
checks['first_outputs_no_source_tuning']=all(hashlib.sha256((OUT/(phase+'-first-run.ndjson')).read_bytes()).hexdigest()==value for phase,value in result['first_run_hashes'].items()) and result['source_or_prompt_tuning_after_first_output'] is False
checks['original_user_acceptance_stays_null']=result['user_acceptance'] is None
checks['strict_basis_failures_preserved']=result['regression']['strict_supported_final_coverage']=={'numerator':1,'denominator':6,'value':1/6} and result['regression']['all_contract_invalid_writes_among_applied']=={'numerator':1,'denominator':2,'value':0.5}
value={'at':datetime.now(UTC).isoformat(),'runtime_revision':revision,'engineering_retention_accounting_checks':checks,'all_delivery_integrity_checks_passed':all(checks.values()),'deployed_sources':len(actual),'old_readable_details':len(old),'current_readable_details':len(new),'natural_reading_additions':sorted(set(new)-set(old)),'protected_r204_files':len(pre['observation']['retained_files']),'r204_window_review_not_accepted_by_this_batch':True,'production_enabled':False,'real_model_technical_pass':result['overall_technical_pass'],'r206_complete':False}
with (OUT/'delivery.json').open('x') as f:json.dump(value,f,indent=2)
print(json.dumps(value,indent=2));assert all(checks.values())
