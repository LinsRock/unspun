"""Freeze retained real R2 inputs and two additive real anchors before any paid request."""
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session
from unspun.core.config import get_settings
from unspun.core.content import fingerprint
from unspun.core.content_publication import qualified_item
from unspun.core.member_contracts import member_contract
from unspun.core.models import Article, ContentMaterial, ContentDerivation
from unspun.core.sources import load_sources
from unspun.pipeline.content_processing import load_content
ROOT=Path(__file__).resolve().parents[3]
OUT=ROOT/'docs/evaluations/r2'
assert not (OUT/'member-freeze-v1.json').exists(), 'frozen registration is append-only'
base=json.loads((ROOT/'docs/acceptance/r2-01/production.json').read_text())
inputs=json.loads((OUT/'inputs-v1.json').read_text())['candidates']
packages=[]
for item in inputs:
    content=item['input']
    article=next(a for a in base['articles'] if a['id']==content['article_id'])
    material=next(m for m in base['materials'] if m['id']==content['material_id'])
    material={k:v for k,v in material.items() if k in ContentMaterial.__table__.columns.keys()}
    material.update(paragraphs=content['paragraphs'], evidence={})
    derivations=[d for d in base['derivations'] if d['article_id']==article['id'] and d['material_id']==material['id']]
    packages.append({'id':item['id'],'split':item['split'],'origin':'frozen-r2-01-v1','observed_state':item['observed_state'],'original_input':content,'article':article,'material':material,'derivations':derivations})
e=create_engine('postgresql+psycopg://unspun:unspun@localhost:5432/unspun_r206_prod_restore_20261020')
with e.connect() as c:
    c.execute(text('SET TRANSACTION READ ONLY'));s=Session(bind=c)
    for identity in (8903,8985):
        item=qualified_item(s,identity,preview=False,as_of=datetime.now(UTC),sources=load_sources())
        assert item is not None
        article=dict(s.execute(select(Article.__table__).where(Article.id==identity)).mappings().one())
        material=dict(s.execute(select(ContentMaterial.__table__).where(ContentMaterial.id==article['current_material_id'])).mappings().one())
        derivations=[dict(r) for r in s.execute(select(ContentDerivation.__table__).where(ContentDerivation.article_id==identity,ContentDerivation.material_id==material['id'])).mappings()]
        packages.append({'id':'R2-'+str(identity),'split':'holdout' if identity==8985 else 'regression','origin':'retained-production-restore-000019','observed_state':'currently_qualified','original_input':load_content(s,identity).model_dump(mode='json'),'article':article,'material':material,'derivations':derivations})
    c.rollback()
pack={'schema_version':'r206-real-input-packages-v1','frozen_at':datetime.now(UTC).isoformat(),'identity_mapping':'Keep article IDs; material and derivation IDs use 100000 + origin ID to avoid overwriting prior evaluation objects. R1 processing fingerprints do not contain those IDs. Original inputs and all evidence remain unchanged.','packages':packages}
(OUT/'member-inputs-v1.json').write_text(json.dumps(pack,ensure_ascii=False,default=str,indent=2)+'\n')
topics=[]
def topic(key,kind,title,anchor,split,relation='report'):
    topics.append({'key':key,'id':str(uuid5(NAMESPACE_URL,'unspun-r206-real-v1:'+key)),'kind':kind,'title':title,'anchors':[anchor],'split':split,'seed_relation':relation})
topic('france','event','France nationwide protests and riots, October 2026',8868,'regression')
topic('huang','event','Investigation of Huang Ribo announced October 18, 2026',8879,'regression')
topic('canada','event','Wainwright military base fire reported as September 17 in retained anchor',8878,'regression')
topic('mercenary','issue','Ownership and activities of the inherited Wagner mercenary force',8861,'regression')
topic('westbank','issue','Israeli settler violence against Palestinians and visitors in the West Bank',8872,'regression')
topic('hongkong','event','Hong Fuk Court fire and official accountability in Hong Kong',8903,'regression','opinion')
topic('uzbekistan','event','Li Qiang meetings with Uzbekistan leaders during the Central Asia visit',8876,'holdout')
topic('tajikistan','event','Li Qiang talks with Tajikistan prime minister Rasulzoda',8985,'holdout')
topic('deepseek','event','DeepSeek new model release reported October 2026',8896,'holdout')
topic('japan-era','issue','Japanese era names and the historical East Asian era naming system',8904,'holdout','explanation')
queries=[]
def query(identity,split,expected,dimensions):
    queries.append({'article_id':identity,'split':split,'expected_associations':expected,'dimensions':dimensions,'unlisted_topics':'independent; report every selected negative candidate as well','user_accepted':None})
query(8881,'regression',{'france':['same_event']},['cross_language','unknown_original_time'])
query(8898,'regression',{'france':['same_event']},['cross_source','same_event'])
query(8899,'regression',{'huang':['opinion','background']},['independent_analysis','opinion_attribution'])
query(8905,'regression',{},['conflicting_dates','same_subject_insufficient_identity'])
query(8893,'regression',{'mercenary':['same_issue','background'],'westbank':['same_issue','background']},['partial_overlap','multi_topic','preview'])
query(8874,'regression',{},['long_input','independent_knowledge'])
query(8877,'holdout',{},['independent_opinion','review'])
query(8906,'holdout',{'tajikistan':['same_event']},['same_person_distinct_events','positive_holdout'])
query(8876,'holdout',{},['same_person_distinct_events','negative_holdout','existing_member_excluded'])
query(8923,'holdout',{},['same_country_distinct_subjects'])
query(8926,'holdout',{},['same_country_distinct_events'])
pre=json.loads((ROOT/'docs/acceptance/r2-06-evaluation/prepay-evaluation.json').read_text())
prod=json.loads((ROOT/'docs/acceptance/r2-06-evaluation/predeploy-production.json').read_text())
reg={'schema_version':'r206-real-registration-v1','id':'r206-real-v1','frozen_at':datetime.now(UTC).isoformat(),'base_revision':'c58a87881017a3b0b2e89de15bbf32279b9e6b39','contract':member_contract(),'database':'unspun_quality_r1_20261016','original_inputs':30,'supplemental_inputs':2,'topics':topics,'queries':queries,'execution_order':'listed regression then holdout; no tuning after any live output; first results retained even on failure','anchor_policy':'Manual AI technical seeds from actual qualified originals; at most two currently valid anchors in first 32 active members by article ID. Applied query members may become later anchors; never inject expected candidates. Topic domains come from seed cards.','metrics':{'candidate_recall':'eligible expected article-topic pairs reaching vector top4 / all eligible expected article-topic pairs, plus losses at admission, domain, SQL32, anchor32, metadata12, vector4','judgment_precision':'correct associated classifications / all certain associated judgments; also binary correctness across every selected positive and negative pair','member_coverage':'correct actually applied expected article-topic pairs / all eligible expected pairs; also query coverage','false_merge':'incorrect applied associations / all applied associations; negative-pair rate reported separately','review':'rejected / all reviewed associations; unsupported judgments blocked / all unsupported reviewed judgments; stale CAS and structural rejection separate'},'technical_gates':{'candidate_recall_min':0.90,'judgment_precision_min':0.95,'final_member_coverage_min':0.80,'false_merges_max':0,'unapproved_or_invalid_applied_max':0,'all_required_real_dimensions_covered':True,'thresholds_are':'AI technical acceptance, not user approval'},'budget':{'project_limit_usd':'15','original_evaluation_limit_usd':'1.50','batch_limit_usd':'0.20','physical_request_limit':120,'stage_physical_limits':{'topic_embedding':24,'topic_judgment':64,'topic_review':32},'stage_caps_usd':{'topic_embedding':'0.02','topic_judgment':'0.08','topic_review':'0.20'},'stage_caps_meaning':'Overlapping stage ceilings within ONE pooled batch cap of 0.20; not additive credits. Conservative per-call holds remain unchanged.','guard':'Every physical request including internal retry is checked against original cumulative budget, pooled new known+new pending, per-stage and total call caps. Any new unknown halts the batch; no retry or original hold release. Resume reconstructs spent/counts from the same DB and takes an exclusive advisory lock.','baseline_accounting':pre['budget']['accounting'],'baseline_unknown_requests':pre['unknown_requests'],'provider':prod['provider'],'available_evaluation_usd':'0.64612299999999994','effective_batch_limit_usd':'0.20'},'missing_real_cases':[{'dimension':'verified_reprint_chain','status':'missing','reason':'No verified exact reprint chain among original or supplemental qualified materials. Attribution to a wire service is not exact reprint proof.'},{'dimension':'recently_discovered_old_original_background','status':'missing','reason':'Long 8874 input and 8903 fire opinion do not prove an old original publication. No synthetic substitute.'},{'dimension':'independently_verified_event_occurrence_time','status':'missing','reason':'Feed/observation time is not an occurrence timestamp.'}],'user_approval':{'ratings':None,'membership_acceptance':None,'basis':'No new user labels; original empty user-review-v1 remains frozen.'},'excluded_original_inputs':[{'id':p['id'],'reason':p['observed_state']} for p in packages if p['observed_state'] not in ('currently_published','currently_qualified')],'no_paid_regeneration':True,'production_enabled':False}
(OUT/'member-registration-v1.json').write_text(json.dumps(reg,ensure_ascii=False,default=str,indent=2)+'\n')
paths=['docs/evaluations/r2/member-inputs-v1.json','docs/evaluations/r2/member-registration-v1.json','docs/evaluations/r2/freeze-v1.json','docs/evaluations/r2/relations-v1.json']
manifest={'schema_version':'r206-real-freeze-v1','frozen_at':datetime.now(UTC).isoformat(),'paid_requests_so_far':0,'files':[{'path':p,'sha256':hashlib.sha256((ROOT/p).read_bytes()).hexdigest()} for p in paths]}
(OUT/'member-freeze-v1.json').write_text(json.dumps(manifest,indent=2)+'\n')
print('Frozen',len(packages),'inputs,',len(topics),'topics,',len(queries),'queries; no paid calls')
