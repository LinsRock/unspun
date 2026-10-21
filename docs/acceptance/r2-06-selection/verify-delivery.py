"""Verify disabled delivery and preserved originals, explicitly accounting for ambient R1."""
import gzip
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

OUT = Path(__file__).parent
ROOT = OUT.parents[2]


def read(name):
    p = OUT / (name + '.json')
    return json.loads(p.read_bytes() if p.exists() else gzip.decompress(p.with_suffix('.json.gz').read_bytes()))


revision = read('core-merged')['mergeCommit']['oid']
ci = read('core-main-ci')
assert ci['headSha'] == revision and ci['conclusion'] == 'success'
assert read('core-pr-ci')['conclusion'] == 'success'
job = next(j for j in ci['jobs'] if j['name'] == 'deploy')
assert job['conclusion'] == 'success'
assert next(s for s in job['steps'] if s['name'] == 'Deploy')['conclusion'] == 'success'
runtime = read('postdeploy-runtime')
assert runtime['health'] == {'status': 'ok', 'version': revision, 'database': 'ok'}
assert runtime['legacy_workers'] == 0 and runtime['r1_workers'] == 1
containers = {v['name']: v for v in runtime['running_containers']}
old_containers = {v['name']: v for v in read('predeploy-runtime')['running_containers']}
for service in ('unspun-api-1', 'unspun-r1-worker-1'):
    assert containers[service]['app_version'] == revision and containers[service]['status'] == 'running'
assert containers['unspun-api-1']['image_id'] == containers['unspun-r1-worker-1']['image_id']
assert containers['unspun-web-1'] == old_containers['unspun-web-1']
local = {str(p.relative_to(ROOT / 'server/src/unspun')): hashlib.sha256(p.read_bytes()).hexdigest()
         for p in (ROOT / 'server/src/unspun').rglob('*.py')}
assert runtime['api_metadata']['source_sha256'] == local
assert runtime['api_metadata']['config_sha256'] == read('predeploy-runtime')['api_metadata']['config_sha256']
chain = read('postdeploy-member-chain')
assert chain['schema'] == '000019'
assert not chain['configured_member_processing_enabled'] and not chain['runtime']['member_processing_enabled']
assert chain['member_handlers'] == chain['topic_tasks'] == chain['topic_calls'] == []
assert len(chain['tables']) == 7 and all(v['rows'] == 0 for v in chain['tables'].values())
assert chain['policy'] == read('predeploy-member-chain')['policy']
assert not any(k.startswith('topic_') for k in chain['policy']['stage_caps'])
for key in ('settings', 'runtime', 'retired_module_present', 'fixture_directory_present'):
    assert read('predeploy-boundaries')[key] == read('postdeploy-boundaries')[key]

# Reconcile the observed delta without a provider call, settlement or guessed fee.
activity = read('ambient-production-activity')
calls = activity['calls']
assert activity['read_only'] == 'on' and activity['provider_queries'] == activity['database_writes'] == 0
assert len(calls) == 7 and all(v['stage'] == 'card' and v['strategy_version'] == 'r1-card-v9' for v in calls)
assert all(datetime.fromisoformat(v['ended_at']) < datetime.fromisoformat(containers['unspun-r1-worker-1']['started_at'].replace('Z', '+00:00')) for v in calls)
known = [v for v in calls if v['status'] == 'responded']
unknown = [v for v in calls if v['status'] == 'usage_unknown']
known_usd = sum((Decimal(str(v['cost_usd'])) for v in known), Decimal(0))
new_holds = sum((Decimal(v['reserved_usd']) for v in unknown), Decimal(0))
assert len(known) == 5 and known_usd == Decimal('0.004403')
assert len(unknown) == 2 and new_holds == Decimal('0.058169') and all(v['http_status'] == 429 for v in unknown)
ledgers = {}
for name in ('production', 'evaluation'):
    before, after = read('predeploy-' + name), read('postdeploy-' + name)
    assert after['transaction']['read_only'] == 'on'
    assert after['paid_requests'] == after['database_writes'] == 0 and 'provider' not in before and 'provider' not in after
    assert before['policy'] == after['policy'] and before['carry'] == after['carry']
    prior = {v['id']: v for v in before['unknown_requests']}
    current = {v['id']: v for v in after['unknown_requests']}
    assert all(current[k] == v for k, v in prior.items())
    if name == 'evaluation':
        assert before['known_ledger'] == after['known_ledger'] and prior == current
    else:
        assert set(current) - set(prior) == {v['id'] for v in unknown}
        b, a = before['known_ledger'][0], after['known_ledger'][0]
        assert a['requests'] - b['requests'] == len(known)
        assert Decimal(a['known_usd']) - Decimal(b['known_usd']) == known_usd
    ledgers[name] = {'unknown_count': len(current), 'held_usd': sum((Decimal(v['reserved_usd']) for v in current.values()), Decimal(0))}
assert ledgers['production'] == {'unknown_count': 12, 'held_usd': Decimal('0.489258')}
assert ledgers['evaluation'] == {'unknown_count': 8, 'held_usd': Decimal('0.514613')}
assert all(v['usage_id'] is None and v['reconciliation'] is None for v in activity['unresolved'])
protected = read('predeploy-protected-production')['queries']
after = read('postdeploy-protected-production')['queries']
for key in protected:
    if key not in ('usage', 'unknown'):
        assert protected[key]['rows'] == after[key]['rows'], key

retained = read('predeploy-retained')['tables']
after = read('postdeploy-retained')['tables']
extra = read('ambient-retention')
assert extra['read_only'] == 'on' and extra['provider_queries'] == extra['database_writes'] == 0
for table in retained:
    if table in ('content_identities', 'content_urls'):
        assert extra['preserved_prefixes'][table] == retained[table]
        assert after[table]['rows'] == retained[table]['rows'] + len(extra['new_rows'][table])
    else:
        assert after[table] == retained[table]
before_read, after_read = read('predeploy-reading'), read('postdeploy-reading')
assert after_read['read_only'] == 'on' and after_read['paid_requests'] == after_read['database_writes'] == 0
old_details = {v['id']: v for v in before_read['qualified_details_verified']}
new_details = {v['id']: v for v in after_read['qualified_details_verified']}
assert len(old_details) == 151 and len(new_details) == 153
assert all(new_details[k] == v for k, v in old_details.items())
assert set(after_read['published_ids']) - set(before_read['published_ids']) == set(new_details) - set(old_details) == {9058, 9282}
assert set(before_read['published_ids']).issubset(after_read['published_ids'])
assert {v['article_id'] for v in extra['card_calls']} == {9058, 9282}
assert all(v['id'] in {c['id'] for c in known} for v in extra['card_calls'])
for key in ('new_path_published', 'suspended_nyt_status'):
    assert before_read[key] == after_read[key]
observation = read('predeploy-observation')
assert observation['containers'] == read('postdeploy-observation')['containers']
assert observation['retained_files'] == read('postdeploy-observation')['retained_files']
assert read('before-recovery')['snapshot'] == read('after-recovery')['snapshot']
assert read('after-recovery')['all_table_counts_hashes_sequences_match']
manifest = read('protected-manifest')
for name, sha in manifest['files'].items():
    assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == sha, name
worktree = manifest['protected_worktree']
assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=worktree['path'], text=True).strip() == worktree['head']
assert subprocess.check_output(['git', 'status', '--porcelain'], cwd=worktree['path'], text=True) == worktree['status']
assert read('validation')['regression_passed'] == 1164 and read('validation')['skipped'] == 0
assert read('freeze-verification')['ranking_identical'] is True
original = json.loads((ROOT / 'docs/acceptance/r2-06-zero-paid/ledger-audit.json').read_text())
assert sum((Decimal(v['reserved_usd']) for v in original['evaluation']['rows'] if v['protected_original_seven']), Decimal(0)) == Decimal('0.484867')
result = {
    'at': datetime.now(UTC).isoformat(), 'production_revision': revision,
    'delivery_checks': 'passed_with_explicit_ambient_r1_activity',
    'source_hashes_match': len(local), 'schema': '000019', 'production_member_enabled': False,
    'member_tasks': 0, 'member_calls': 0, 'empty_member_tables': 7, 'new_stage_allocations': 0,
    'legacy_workers': 0, 'r1_workers': 1, 'protected_original_details_unchanged': 151,
    'qualified_detail_count': 153, 'ambient_new_published_ids': [9058, 9282],
    'reader_event_tables_unchanged': [k for k in retained if k not in extra['preserved_prefixes']],
    'original_identity_url_rows_unchanged': {k: v['rows'] for k, v in extra['preserved_prefixes'].items()},
    'live_first_two_pages_identical': False, 'legacy_frozen_ranking_cases_identical': 40,
    'r204_containers_unchanged': len(observation['containers']), 'r204_original_files_unchanged': len(observation['retained_files']),
    'r204_worktree_unchanged': True, 'protected_artifacts_unchanged': len(manifest['files']),
    'original_evaluation_all_tables_and_sequences_unchanged': True, 'original_holds_preserved': True,
    'production_unknown_count': 12, 'production_holds_usd': '0.489258',
    'evaluation_unknown_count': 8, 'evaluation_holds_usd': '0.514613', 'original_seven_holds_usd': '0.484867',
    'whole_production_window_zero_paid': False,
    'ambient_r1_before_deployment': {'physical_calls': 7, 'known_calls': 5, 'known_usd': str(known_usd), 'new_unknown_calls': 2, 'new_holds_usd': str(new_holds)},
    'paid_scope': 'this R2-06 work only; ambient existing R1 activity is explicitly separate',
    'paid_generation': 0, 'paid_embedding': 0, 'paid_retries': 0, 'provider_queries': 0,
    'new_blind_prepared_or_read': False, 'paid_stop_unchanged': True,
    'semantic_pass': False, 'r206_status': '2/4', 'user_acceptance': None,
}
with (OUT / 'final-audit.json').open('x') as f:
    json.dump(result, f, indent=2)
print(json.dumps(result, indent=2))
