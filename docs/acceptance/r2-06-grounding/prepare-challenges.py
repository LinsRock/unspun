"""Register adversarial decisions over genuine exposed originals, never synthetic material."""
import hashlib,json
from datetime import UTC,datetime
from pathlib import Path
from uuid import NAMESPACE_URL,uuid5
from sqlalchemy import text
from sqlalchemy.orm import Session
from unspun.core.content import fingerprint
from unspun.core.db import get_engine
from unspun.core.member_contracts import REFERENCE_VERSION,project_material
from unspun.core.member_recall import current_input
from unspun.core.sources import load_sources
ROOT=Path(__file__).resolve().parents[3];REG=ROOT/'docs/evaluations/r2'
base=json.loads((REG/'member-grounding-exposed-v1.json').read_text());bykey={t['key']:t for t in base['topics']};topics={};cases=[]
def topic(case,key):
 t=dict(bykey[key]);t.update(key=case,id=str(uuid5(NAMESPACE_URL,'r206-grounding-v1:challenge:'+case)),split='review_challenge');topics[case]=t;return t
with Session(get_engine()) as s:
 s.execute(text('SET TRANSACTION READ ONLY'))
 def snapshot(i):return current_input(s,i,load_sources(),datetime.now(UTC))
 def fact(snap,role,text_value,paragraph=0,voice=None):
  p=project_material(snap,role)['content']['paragraphs'][paragraph]
  choice=next((r for r in p['references'] if voice is None or r['voice']==voice),None)
  assert choice
  return {'text':text_value,'citations':[{'reference_id':choice['reference_id'],'quote':p['text'][:400]}]}
 def add(case,key,query,qtext,atext,inference,classification,expected,qpara=0,apara=0):
  t=topic(case,key);q=snapshot(query);a=snapshot(t['anchors'][0])
  dec={'classification':classification,'certainty':'certain','query_facts':[fact(q,'query',qtext,qpara)],'anchor_facts':[fact(a,'anchor',atext,apara)],'relation_inferences':[{'text':inference,'query_fact_indices':[0],'anchor_fact_indices':[0]}]}
  row={'id':case,'article_id':query,'topic_id':t['id'],'decision':dec,'expected_status':expected,'natural_end_to_end':False,'decision_origin':'Explicit manual challenge over genuine admitted originals; no model judgment.'};cases.append(row);return row
 add('anchor-as-query','mercenary',8893,'The query explicitly names the Wagner mercenary force.','The anchor concerns the son of the Wagner Group founder.','Both cover the continuing mercenary-force succession issue.','same_issue','rejected')
 add('date-conflict','canada',8905,'The query places the Wainwright fire on October 17.','The anchor places the Wainwright fire on September 17.','The September date is a typo because the feed dates align with October.','same_event','rejected',qpara=1,apara=1)
 add('analysis-as-report','huang',8899,'The query includes observer analysis of Huang Ribo being investigated.','The anchor reports that Huang Ribo is under investigation.','The query contributes only the same announcement report, not context or observer analysis.','same_event','rejected')
 wrong=add('invalid-voice','france',8881,'The query reports French protests turning violent.','The media description concerns protests across France.','Both report the same protests.','same_event','failed')
 a=snapshot(topics['invalid-voice']['anchors'][0]);p=project_material(a,'anchor')['content']['paragraphs'][0]
 wrong['decision']['anchor_facts'][0]['citations'][0]['reference_id']='ref_'+fingerprint([REFERENCE_VERSION,fingerprint(a),'anchor',0,p['text'],'reported'])[:24]
 wrong['pre_llm_failure']='scope-forbidden reported-voice reference ID is not in the server catalog'
 wrong=add('invalid-paragraph','huang',8899,'The query includes analysis of Huang Ribo being investigated.','The anchor reports that Huang Ribo is under investigation.','This contextual analysis is background to the investigation.','background','failed')
 a=snapshot(topics['invalid-paragraph']['anchors'][0]);p=project_material(a,'anchor')['content']['paragraphs'][1]
 wrong['decision']['anchor_facts'][0]['citations'][0]['reference_id']=p['references'][0]['reference_id']
 wrong['pre_llm_failure']='paragraph-one reference with an exact quote copied from paragraph zero'
 add('correct-complete','tajikistan',8906,'Li Qiang met Rasulzoda in Dushanbe on October 18.','Li Qiang met Rasulzoda in Dushanbe on October 18.','Both report the same October 18 meeting between the same participants.','same_event','applied',qpara=1)
 replay=add('stale-audit-replay','tajikistan',8906,'Li Qiang met Rasulzoda in Dushanbe on October 18.','Li Qiang met Rasulzoda in Dushanbe on October 18.','Both report the same October 18 meeting between the same participants.','same_event','rejected',qpara=1)
 replay['replay_actual_review_from']='correct-complete';replay['new_reviewer_http_calls']=0
 first=add('cas-race','france',8881,'The query reports protests turning violent in French cities.','The media description concerns protests across France.','Both concern the same nationwide French protests and disorder.','same_event','applied_or_stale')
 first['id']='cas-race-a';first['cas_competition_group']='france-two-actual-reviews'
 second=json.loads(json.dumps(first));second.update(id='cas-race-b',article_id=8898)
 second['decision']['query_facts']=[fact(snapshot(8898),'query','The query reports large French protests and escalating disorder.')]
 cases.append(second)
value={'schema_version':'r206-grounding-challenges-v1','id':'r206-grounding-v1:challenge','topics':list(topics.values()),'queries':[{'article_id':i,'split':'review_challenge'} for i in sorted({c['article_id'] for c in cases})],'input_sources':base['input_sources'],'cases':cases,'population':{'registered_cases':9,'structural_pre_llm_cases':2,'paid_or_actual_review_cases':7,'same_topic_two_query_actual_cas_competition':True},'natural_end_to_end':False,'material_origin':'Only the exact existing exposed originals; injected decisions are challenge artifacts and never natural quality.','user_acceptance':None,'production_enabled':False}
path=REG/'member-grounding-challenges-v1.json'
with path.open('x') as f:json.dump(value,f,ensure_ascii=False,indent=2)
print({'cases':len(cases),'topics':len(topics),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'paid_requests':0,'database_writes':0})
