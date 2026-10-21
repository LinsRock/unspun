"""Read captured PR/CI/runtime evidence before permitting the reviewed paid entry."""
import hashlib,json
from datetime import UTC,datetime
from pathlib import Path
from unspun.core.content import fingerprint
from unspun.core.member_contracts import member_contract
ROOT=Path(__file__).resolve().parents[3];OUT=Path(__file__).parent
def read(n):return json.loads((OUT/(n+'.json')).read_text())
merge=read('preparation-merged');ci=read('preparation-main-ci');pr=read('preparation-pr-ci');runtime=read('postdeploy-runtime');chain=read('postdeploy-member-chain');audit=read('postdeploy-audit')
revision=merge['mergeCommit']['oid'];expected={str(p.relative_to(ROOT/'server/src/unspun')):hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'server/src/unspun').rglob('*.py')}
assert merge['state']=='MERGED' and pr['conclusion']==ci['conclusion']=='success' and ci['headSha']==revision
assert any(j['name']=='deploy' and j['conclusion']=='success' and any(s['name']=='Deploy' and s['conclusion']=='success' for s in j['steps']) for j in ci['jobs'])
assert runtime['health']['version']==revision and runtime['api_metadata']['source_sha256']==expected and len(expected)==95
assert read('predeploy-runtime')['api_metadata']['config_sha256']==runtime['api_metadata']['config_sha256']
assert chain['schema']=='000019' and not chain['configured_member_processing_enabled'] and not chain['runtime']['member_processing_enabled']
assert chain['member_handlers']==chain['topic_tasks']==chain['topic_calls']==[]
assert len(chain['tables'])==7 and all(t['rows']==0 for t in chain['tables'].values())
assert all(k not in chain['policy']['stage_caps'] for k in ['topic_embedding','topic_judgment','topic_review'])
assert audit['legacy_all_states']==0 and audit['controlled_running']==1
assert read('postdeploy-observation')['containers']==read('predeploy-observation')['containers']
assert all(read('postdeploy-observation')['retained_files'].get(k)==v for k,v in read('predeploy-observation')['retained_files'].items())
execution=json.loads((ROOT/'docs/evaluations/r2/member-grounding-budget-v1.json').read_text());assert execution['contract']==member_contract()
proof={'at':datetime.now(UTC).isoformat(),'pr_url':merge['url'],'merge_revision':revision,'pr_ci_url':pr['url'],'main_ci_url':ci['url'],'pr_ci_passed':True,'main_ci_deployed':True,'deployed_source_hashes_match':True,'deployed_source_files':95,'source_freeze_sha256':hashlib.sha256((ROOT/'docs/evaluations/r2/member-grounding-freeze-v1.json').read_bytes()).hexdigest(),'execution_fingerprint':fingerprint(execution),'production_enabled':False,'production_member_tasks':0,'production_member_calls':0,'new_production_stage_allocations':0,'new_production_tables_empty':7,'schema':'000019','r204_containers_and_old_files_unchanged':True,'new_paid_requests_before_proof':0}
with (OUT/'paid-entry-review-proof.json').open('x') as f:json.dump(proof,f,indent=2)
print(json.dumps(proof,indent=2))
