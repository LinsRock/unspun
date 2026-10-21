"""SELECT-only complete-basis review projection of all actually reviewed v4 decisions."""
import json
from pathlib import Path
from sqlalchemy import select,text
from sqlalchemy.orm import Session
from unspun.core.db import get_engine
from unspun.core.member_contracts import member_contract
from unspun.core.member_evidence import reference_catalog
from unspun.core.member_models import MemberJudgment
from unspun.core.task_models import PipelineTask
from unspun.evaluation.member_grounding import EVIDENCE
with Session(get_engine()) as s:
 s.execute(text('SET TRANSACTION READ ONLY'));tasks={t.id:t for t in s.scalars(select(PipelineTask))};out=[]
 for row in s.scalars(select(MemberJudgment).order_by(MemberJudgment.task_id)):
  t=tasks[row.task_id]
  if t.strategy_version!=member_contract()['version'] or not row.review:continue
  catalog=reference_catalog(row.input_snapshot);decision=row.decision;facts=[]
  for role in ['query','anchor']:
   for i,fact in enumerate(decision[role+'_facts']):
    facts.append({'target':role+'_facts/'+str(i),'claim':fact['text'],'citations':[{**citation,'server_expanded':catalog.get(citation['reference_id'])} for citation in fact['citations']]})
  out.append({'task_id':row.task_id,'article_id':row.article_id,'topic_id':row.topic_id,'status':row.status,'judgment_fingerprint':row.input_fingerprint,'classification':decision['classification'],'facts':facts,'relation_inferences':decision['relation_inferences'],'basis':None,'review':row.review,'source_titles':{'query':row.input_snapshot['query']['content']['title'],'anchors':[a['snapshot']['content']['title'] for a in row.input_snapshot['candidate']['topic']['anchors']]}})
 with (EVIDENCE/'strict-review-packets.json').open('x') as f:json.dump(out,f,indent=2,ensure_ascii=False)
 print(json.dumps([{k:v for k,v in r.items() if k not in ['review','basis']} for r in out],ensure_ascii=False,indent=2))
