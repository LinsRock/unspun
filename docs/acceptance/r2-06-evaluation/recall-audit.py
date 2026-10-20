"""Compare retained v1 and v2 real pre-embedding plans in an isolated rollback."""
import json
import subprocess
import types
from datetime import UTC,datetime
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from unspun.core.config import get_settings
from unspun.core.member_recall import recall_plan
from unspun.core.sources import load_sources
from unspun.evaluation.member_quality import registration,seed_packages,seed_topics
ROOT=Path(__file__).resolve().parents[3];OUT=Path(__file__).parent
assert get_settings().database_url.endswith('/unspun_r206_eval_tests_20261020')
old=types.ModuleType('retained_recall_v1')
exec(compile(subprocess.check_output(['git','show','c58a878:server/src/unspun/core/member_recall.py'],cwd=ROOT),'<v1-recall>','exec'),old.__dict__)
spec=registration();packages=json.loads((ROOT/'docs/evaluations/r2/member-inputs-v1.json').read_text())
sources=load_sources();engine=create_engine(get_settings().database_url);result=[]
with engine.connect() as conn,conn.begin() as tx,Session(bind=conn) as s:
    seed_packages(s,packages['packages']);seed_topics(s,spec,sources)
    for q in spec['queries']:
        before=old.recall_plan(s,q['article_id'],sources,datetime.now(UTC));after=recall_plan(s,q['article_id'],sources,datetime.now(UTC))
        names={t['id']:t['key'] for t in spec['topics']}
        result.append({'article_id':q['article_id'],'split':q['split'],'card_topics':after['query']['qualification']['card']['payload']['topics'],'old_pre_embedding_topic_keys':[names[t['id']] for t in before['topics']],'new_pre_embedding_topic_keys':[names[t['id']] for t in after['topics']],'expected':q['expected_associations'],'new_trace':after['trace'],'vector_stage':'unmeasured before paid embedding; no expected candidates injected'})
    tx.rollback()
report={'at':datetime.now(UTC).isoformat(),'database':'unspun_r206_eval_tests_20261020','old_source_revision':'c58a878','real_plans':result,'paid_calls':0,'formal_evaluation_database_writes':0,'all_seed_writes_rolled_back':True,'synthetic_old_failures_retained':[{'case':'empty_card_topics','old':'same timestamp leaves subjects tied and ID order wins','new':'original-material subject signal ranks same-subject first','evidence':'test_optional_empty_card_terms_use_original_material'},{'case':'uuid32','old':'relevant high UUID excluded before ranking','new':'subject-title SQL rank includes it within 32','evidence':'test_subject_ranking_precedes_uuid_32_cutoff'},{'case':'first_two_stale_anchors','old':'whole candidate raises stale','new':'later valid member retained within 32 checked members','evidence':'test_skip_first_two_stale_anchors_within_bounded_scan'},{'case':'unknown_old_competition','old':'both old/unknown lost to recent 12','new':'both retained in bounded 12','evidence':'test_unknown_and_old_background_survive_competing_recent_topics'}]}
with (OUT/'prepay-recall-audit.json').open('x') as f:json.dump(report,f,ensure_ascii=False,default=str,indent=2)
print('Real pre-embedding plans:',len(result),'paid calls: 0')
