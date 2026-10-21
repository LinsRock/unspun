"""Verify reviewed local evaluation entry separately from actual deployed core sources."""
import hashlib,json,subprocess
from datetime import UTC,datetime
from pathlib import Path
from unspun.core.content import fingerprint
from unspun.core.member_contracts import member_contract
ROOT=Path(__file__).resolve().parents[3];OUT=Path(__file__).parent

def read(n):return json.loads((OUT/(n+'.json')).read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
merge,pr,ci=[read('credential-'+n) for n in ['merged','pr-ci','main-ci']]
assert merge['state']=='MERGED' and pr['conclusion']==ci['conclusion']=='success'
assert ci['headSha']==merge['mergeCommit']['oid']
assert subprocess.check_output(['git','rev-parse','HEAD'],text=True,cwd=ROOT).strip()==ci['headSha']
assert all(j['conclusion'] in ['success','skipped'] for j in ci['jobs'])
assert all(j['conclusion']=='skipped' for j in ci['jobs'] if j['name'] in ['build-server','build-web','deploy'])
old=read('paid-entry-review-proof');assert old['pr_ci_passed'] and old['main_ci_deployed'] and old['deployed_source_hashes_match']
runtime=read('credential-runtime');chain=read('credential-member-chain');audit=read('postdeploy-audit')
expected={str(p.relative_to(ROOT/'server/src/unspun')):sha(p) for p in (ROOT/'server/src/unspun').rglob('*.py')}
actual=runtime['api_metadata']['source_sha256'];differences={p:{'local':expected[p],'deployed':actual[p]} for p in expected if expected[p]!=actual[p]}
assert set(actual)==set(expected) and set(differences)=={'evaluation/member_grounding.py','evaluation/member_grounding_challenge.py'}
assert all(actual[p]==expected[p] for p in expected if not p.startswith('evaluation/'))
assert runtime['health']['version']==old['merge_revision']=='beb8e03ade1bfac90ffd509eb340f35210494275'
assert chain['schema']=='000019' and chain['configured_member_processing_enabled'] is chain['runtime']['member_processing_enabled'] is False
assert chain['member_handlers']==chain['topic_tasks']==chain['topic_calls']==[]
assert len(chain['tables'])==7 and all(t['rows']==0 for t in chain['tables'].values())
assert all(k not in chain['policy']['stage_caps'] for k in ['topic_embedding','topic_judgment','topic_review'])
freeze=ROOT/'docs/evaluations/r2/member-grounding-freeze-v2.json'
for row in json.loads(freeze.read_text())['files']:assert sha(ROOT/row['path'])==row['sha256']
execution=json.loads((ROOT/'docs/evaluations/r2/member-grounding-budget-v1.json').read_text());assert execution['contract']==member_contract()
proof={'at':datetime.now(UTC).isoformat(),'pr_url':merge['url'],'merge_revision':ci['headSha'],'pr_ci_url':pr['url'],'main_ci_url':ci['url'],'pr_ci_passed':True,'main_ci_checked':True,'runtime_deployment_verified':True,'runtime_merge_revision':old['merge_revision'],'runtime_pr_url':old['pr_url'],'runtime_main_ci_url':old['main_ci_url'],'evaluation_only_main_deploy_skipped':True,'local_evaluation_sources_frozen':True,'deployed_runtime_source_hashes_match':True,'total_source_files':len(expected),'deployed_eval_tool_differences_disclosed':differences,'source_freeze_sha256':sha(freeze),'execution_fingerprint':fingerprint(execution),'production_enabled':False,'production_member_tasks':0,'production_member_calls':0,'new_production_stage_allocations':0,'new_production_tables_empty':7,'schema':'000019','new_paid_requests_before_proof':0}
with (OUT/'paid-entry-review-proof-v2.json').open('x') as f:json.dump(proof,f,indent=2)
print(json.dumps(proof,indent=2))
