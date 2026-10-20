"""SELECT-only layered quality and cost report from every actual frozen-batch candidate."""
import gzip
import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from unspun.core.billing_models import BilledRequest
from unspun.core.db import get_engine
from unspun.core.llm import parse_json_content
from unspun.core.member_contracts import MemberDecision
from pydantic import ValidationError
from unspun.core.member_models import ContentVector, MemberJudgment
from unspun.core.member_recall import vector_input
from unspun.core.models import LlmUsage
from unspun.core.task_models import PipelineTask, TaskAttempt
from unspun.core.topic_models import Topic
from unspun.evaluation.member_quality import registration,require_original_database,batch_state
ROOT=Path(__file__).resolve().parents[3];OUT=Path(__file__).parent
require_original_database();spec=registration()
records=[json.loads(line) for line in (OUT/'first-run.ndjson').read_text().splitlines()]
started={r['article_id']:r for r in records if r['event']=='query'}
keys={t['id']:t['key'] for t in spec['topics']}
reverse={v:k for k,v in keys.items()}
engine=get_engine()
def ratio(n,d):return {'numerator':n,'denominator':d,'value':n/d if d else None}
with engine.connect() as conn,conn.begin():
    conn.execute(text('SET TRANSACTION READ ONLY'));s=Session(bind=conn)
    tasks=list(s.scalars(select(PipelineTask).where(PipelineTask.kind.in_(['topic_recall','topic_judge','topic_review'])).order_by(PipelineTask.id)))
    judgments={r.input_fingerprint:r for r in s.scalars(select(MemberJudgment))}
    bills=list(s.scalars(select(BilledRequest).where(BilledRequest.stage.in_(['topic_embedding','topic_judgment','topic_review'])).order_by(BilledRequest.started_at,BilledRequest.id)))
    usage={r.id:r for r in s.scalars(select(LlmUsage))}
    domains={t.id:set(t.domains) for t in s.scalars(select(Topic))}
    expected=[];inputs=[];layers=Counter()
    for q in spec['queries']:
        event=started.get(q['article_id'])
        if event:
            plan=event['plan'];trace=plan['trace'];card_domains=set(plan['query']['qualification']['card']['payload']['domains'])
            layers['queries_started']+=1
            layers['domain_pairs']+=sum(bool(card_domains.intersection(domains[t])) for t in keys if t not in trace['existing_member_topics'])
            for label,ids in [('sql32_pairs',trace['scanned_topic_ids']),('valid_anchor_pairs',trace['qualified_topic_ids']),('metadata12_pairs',trace['metadata_topic_ids'])]:layers[label]+=len(ids)
            raw='\n'.join(p['text'] for p in plan['query']['content']['paragraphs'])
            vector=vector_input(plan['query'])['text']
            inputs.append({'article_id':q['article_id'],'split':q['split'],'card_topics':plan['query']['qualification']['card']['payload']['topics'],'material_chars':len(raw),'embedding_bytes':len(vector.encode()),'embedding_truncated':len((plan['query']['content']['title']+'\n'+raw[:12000]).encode())>24000,'semantic_truncated':len(raw)>12000,'subject_material_prefix_chars':min(2000,len(raw)),'trace':trace})
        for key,allowed in q['expected_associations'].items():
            target=reverse[key];loss=None
            if not event:loss='not_started_after_batch_halt'
            elif not card_domains.intersection(domains[target]):loss='domain'
            elif target in trace['existing_member_topics']:loss='already_decided'
            elif target not in trace['scanned_topic_ids']:loss='sql32'
            elif target not in trace['qualified_topic_ids']:loss='valid_anchor32'
            elif target not in trace['metadata_topic_ids']:loss='metadata12'
            else:
                selected=[t.payload['candidate']['topic']['id'] for t in tasks if t.kind=='topic_judge' and t.article_id==q['article_id']]
                if target not in selected:
                    recall=next(t for t in tasks if t.id==event['recall_task'])
                    loss='vector4' if recall.status=='completed' else 'recall_execution_'+recall.status
            expected.append({'article_id':q['article_id'],'topic':key,'split':q['split'],'allowed':allowed,'first_recall_loss':loss})
    pairs=[]
    for task in tasks:
        if task.kind!='topic_judge':continue
        topic=keys[task.payload['candidate']['topic']['id']]
        q=next(q for q in spec['queries'] if q['article_id']==task.article_id)
        allowed=q['expected_associations'].get(topic,[])
        row=judgments.get(task.input_fingerprint)
        calls=[b for b in bills if b.task_id==task.id]
        first=None;first_error=None;decision=None
        if calls:
            try:first=parse_json_content(calls[0].response_payload['choices'][0]['message']['content'])
            except (ValueError,TypeError,KeyError,IndexError) as error:first_error=type(error).__name__
        # The full logical decision may follow the unchanged bounded length retry.
        for call in calls:
            try:decision=MemberDecision.model_validate(parse_json_content(call.response_payload['choices'][0]['message']['content']))
            except (ValueError,TypeError,KeyError,IndexError):pass
        # Count every raw certain association, including malformed evidence.
        # Schema failure must not remove a bad prediction from the denominator.
        schema_errors=[]
        try: MemberDecision.model_validate(first)
        except ValidationError as error: schema_errors=error.errors(include_input=False,include_url=False)
        label=first.get('classification') if isinstance(first,dict) else None
        certainty=first.get('certainty') if isinstance(first,dict) else None
        associated=certainty=='certain' and label in {'same_event','same_issue','background','opinion','explanation','reprint'}
        correct_association=bool(associated and label in allowed)
        correct=correct_association if allowed else bool(label=='independent' or certainty=='uncertain')
        review_tasks=[t for t in tasks if t.kind=='topic_review' and t.payload['decision_key']==task.input_fingerprint]
        review_calls=[b for b in bills if any(b.task_id==t.id for t in review_tasks)]
        pairs.append({'article_id':task.article_id,'topic':topic,'split':q['split'],'expected_classifications':allowed,'task_id':task.id,'task_status':task.status,'task_error':task.last_error,'judge_attempted':bool(calls),'first_output':first,'first_output_parse_error':first_error,'schema_errors':schema_errors,'schema_valid':not schema_errors and first is not None,'decision':decision.model_dump(mode='json') if decision else None,'associated':associated,'correct_classification':correct,'operationally_correct':correct and decision is not None and row is not None,'judgment_status':row.status if row else None,'review_attempted':bool(review_calls),'review':row.review if row else None,'applied':bool(row and row.status=='applied'),'correct_applied':bool(row and row.status=='applied' and correct_association),'association_expected':bool(allowed),'call_ids':[b.id for b in calls],'review_call_ids':[b.id for b in review_calls]})
    def metrics(split=None):
        exp=[e for e in expected if split is None or e['split']==split]
        ps=[p for p in pairs if split is None or p['split']==split]
        attempted=[p for p in ps if p['judge_attempted']]
        associated=[p for p in attempted if p['associated']]
        applied=[p for p in ps if p['applied']]
        reviewed=[p for p in ps if p['review_attempted']]
        bad_reviewed=[p for p in reviewed if not p['correct_classification']]
        negatives=[p for p in attempted if not p['expected_classifications']]
        return {'expected_pairs':len(exp),'selected_candidate_pairs':len(ps),'judge_attempted_pairs':len(attempted),'candidate_recall':ratio(sum(e['first_recall_loss'] is None for e in exp),len(exp)),'judgment_precision':ratio(sum(p['correct_classification'] for p in associated),len(associated)),'judgment_accuracy':ratio(sum(p['correct_classification'] for p in attempted),len(attempted)),'schema_valid_judgments':ratio(sum(p['schema_valid'] for p in attempted),len(attempted)),'operational_judgment_accuracy':ratio(sum(p['operationally_correct'] for p in attempted),len(attempted)),'operational_association_precision':ratio(sum(p['operationally_correct'] for p in associated),len(associated)),'raw_false_association_rate':ratio(sum(p['associated'] for p in negatives),len(negatives)),'final_member_coverage':ratio(sum(p['correct_applied'] for p in ps),len(exp)),'wrong_relation_among_expected_applied':ratio(sum(p['association_expected'] and not p['correct_applied'] for p in applied),sum(p['association_expected'] for p in applied)),'binary_final_member_coverage':ratio(sum(p['association_expected'] for p in applied),len(exp)),'false_merge_among_applied':ratio(sum(not p['association_expected'] for p in applied),len(applied)),'false_merge_among_attempted_negatives':ratio(sum(p['applied'] for p in negatives),len(negatives)),'review_rejection':ratio(sum(p['judgment_status']=='rejected' for p in reviewed),len(reviewed)),'unsupported_review_interception':ratio(sum(p['judgment_status']=='rejected' for p in bad_reviewed),len(bad_reviewed)),'structural_judge_failures':sum(p['task_status']=='failed' for p in ps),'stale_cas':sum(p['judgment_status']=='stale' for p in ps),'unprocessed_selected_pairs':sum(not p['judge_attempted'] for p in ps)}
    result=metrics();costs={}
    def query_metrics(split=None):
        qs=[q for q in spec['queries'] if split is None or q['split']==split]
        positive=[q for q in qs if q['expected_associations']]
        correct={(p['article_id'],p['topic']) for p in pairs if p['correct_applied']}
        return {'registered_queries':len(qs),'started_queries':sum(q['article_id'] in started for q in qs),'positive_queries':len(positive),'queries_with_any_correct_member':ratio(sum(any((q['article_id'],key) in correct for key in q['expected_associations']) for q in positive),len(positive)),'queries_with_all_expected_members':ratio(sum(all((q['article_id'],key) in correct for key in q['expected_associations']) for q in positive),len(positive))}

    for stage in ('topic_embedding','topic_judgment','topic_review'):
        rows=[b for b in bills if b.stage==stage];known=sum((Decimal(str(usage[b.usage_id].cost_usd)) for b in rows if b.usage_id),Decimal(0));held=sum((b.reserved_usd for b in rows if b.status in ('reserved','usage_unknown')),Decimal(0))
        costs[stage]={'physical_requests':len(rows),'known_requests':sum(b.usage_id is not None for b in rows),'known_usd':str(known),'held_usd':str(held),'unknown_requests':sum(b.status in ('reserved','usage_unknown') for b in rows),'per_physical_request_usd':str(known/len(rows)) if rows else None}
    known=sum((Decimal(c['known_usd']) for c in costs.values()),Decimal(0));n_applied=sum(p['applied'] for p in pairs);n_correct=sum(p['correct_applied'] for p in pairs)
    gates={'candidate_recall':(result['candidate_recall']['value'] or 0)>=.90,'judgment_precision':(result['judgment_precision']['value'] or 0)>=.95,'member_coverage':(result['final_member_coverage']['value'] or 0)>=.80,'no_false_merge':result['false_merge_among_applied']['numerator']==0,'approved_current_writes_only':all(p['review'] and p['review']['approved'] and not p['review']['issues'] for p in pairs if p['applied']),'required_real_coverage':not spec['missing_real_cases']}
    report={'schema_version':'r206-real-result-v1','at':datetime.now(UTC).isoformat(),'registration_id':spec['id'],'execution_completed':records[-1]['event']=='complete','queries_registered':len(spec['queries']),'queries_started':len(started),'unavailable_inputs':spec.get('unavailable_inputs',[]),'registered_article_topic_pairs_after_existing_seed_exclusion':sum(q['article_id'] not in t['anchors'] for q in spec['queries'] for t in spec['topics']),'layers':dict(layers),'query_coverage':query_metrics(),'metrics':result,'query_coverage_by_split':{split:query_metrics(split) for split in ('regression','holdout')},'by_split':{split:metrics(split) for split in ('regression','holdout')},'expected_pair_losses':expected,'all_candidate_results':pairs,'material_and_trace':inputs,'costs':costs,'new_known_usd':str(known),'batch_state':batch_state(s),'unit_costs':{'per_started_query_usd':str(known/len(started)) if started else None,'per_selected_candidate_pair_usd':str(known/len(pairs)) if pairs else None,'per_applied_member_usd':str(known/n_applied) if n_applied else None,'per_correct_applied_member_usd':str(known/n_correct) if n_correct else None,'basis':'This purposive batch only; includes embedding and negatives. Holds are not paid fees.'},'technical_gates':gates,'overall_technical_pass':all(gates.values()),'missing_real_cases':spec['missing_real_cases'],'user_acceptance':None,'production_enabled':False,'tuning_after_first_output':False,'first_run_sha256':hashlib.sha256((OUT/'first-run.ndjson').read_bytes()).hexdigest(),'member_contract':spec['contract'],'precision_basis':'Raw claimed certain association labels against frozen classifications; all malformed evidence remains in this denominator. Schema validity and executable correctness are separate. No failed output is repaired or inferred.'}
    with (OUT/'results-v1.json').open('x') as f:json.dump(report,f,ensure_ascii=False,default=str,indent=2)
    for name,rows in [('judgments',[dict(r) for r in s.execute(select(MemberJudgment.__table__)).mappings()]),('vectors',[dict(r) for r in s.execute(select(ContentVector.__table__)).mappings()]),('physical-requests',[dict(s.execute(select(BilledRequest.__table__).where(BilledRequest.id==b.id)).mappings().one())|{'known_cost_usd':str(usage[b.usage_id].cost_usd) if b.usage_id else None} for b in bills]),('tasks',[dict(s.execute(select(PipelineTask.__table__).where(PipelineTask.id==t.id)).mappings().one()) for t in tasks]),('attempts',[dict(r) for r in s.execute(select(TaskAttempt.__table__).where(TaskAttempt.task_id.in_([t.id for t in tasks]))).mappings()])]:
        with gzip.open(OUT/(name+'.json.gz'),'xt') as f:json.dump(rows,f,ensure_ascii=False,default=str)
print(json.dumps({'metrics':report['metrics'],'new_known_usd':str(known),'gates':gates},indent=2))
