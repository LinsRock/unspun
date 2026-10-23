"""Offline-only replay over four already exposed, retained qualified originals.

No live-client option: all model responses are explicitly marked MockTransport data.
Run with the isolated URL below after Alembic upgrade; never reads the paid evaluation DB.
"""
import gzip
import hashlib
import json
import os
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4, uuid5, NAMESPACE_URL

import httpx
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from unspun.core.billing import initialize_budget
from unspun.core.billing_models import BudgetPolicy, BilledRequest
from unspun.core.config import get_settings
from unspun.core.content import fingerprint
from unspun.core.content_publication import qualified_item
from unspun.core.models import Article, ContentMaterial, ContentDerivation
from unspun.core.sources import load_sources
from unspun.core.synthesis_contracts import MANUAL_VERSION, ManualReview, text_contract
from unspun.core.synthesis_models import TopicSynthesis
from unspun.core.topic_contracts import DefineTopic, SetMember, TopicMutation, EvidenceRef
from unspun.core.topic_models import Topic, TopicUpdate
from unspun.core.topics import mutate_topic, read_topic
from unspun.core.llm import LlmClient
from unspun.core.tasks import claim, complete
from unspun.evaluation.member_quality import seed_packages
from unspun.pipeline.topic_synthesis import enqueue_synthesis, SynthesisHandler

ROOT = Path(__file__).resolve().parents[3]
EXPECTED = "postgresql+psycopg://unspun:unspun@localhost:5432/unspun_r207_materials_20261023"
assert os.environ.get("UNSPUN_DATABASE_URL") == EXPECTED, "Only the named isolated replay database is allowed"
os.environ.update(UNSPUN_OPENROUTER_API_KEY="r207-offline-mock-only", UNSPUN_R2_SYNTHESIS_ENABLED="true", UNSPUN_R2_TOPIC_PUBLICATION_ENABLED="false")
get_settings.cache_clear()
engine = create_engine(EXPECTED)
sources = load_sources()
artifact = ROOT / "docs/evaluations/r2/member-grounding-exposed-inputs-v1.json.gz"
packages = [p for p in json.loads(gzip.decompress(artifact.read_bytes()))["packages"] if p["original_id"] in {9192,9013,9051,9054}]
by_id = {p["original_id"]: p for p in packages}
reviewer = ManualReview(actor="codex:r2-07-manual-source-review", identity="agent_manual", basis="逐条阅读已暴露保留原文；仅核验成员适用范围，非真人标注、自动归并或真实模型质量")
sets = [
    {"key":"ai-dividend", "title":"AI收益分配方案的报道比较", "domains":["technology"], "members":[(9013,0,"report"),(9192,0,"report")]},
    {"key":"book-commentary", "title":"《我的风暴，我的庇护所》的读后与翻译记录", "domains":["culture"], "members":[(9051,4,"opinion"),(9054,17,"background")]},
]

@contextmanager
def scope():
    with Session(engine) as s, s.begin():
        yield s

def reference(aid, paragraph, voice="reported"):
    p=by_id[aid]
    return {"article_id":aid,"material_id":p["material"]["id"],"paragraph":paragraph,"quote":p["original_input"]["paragraphs"][paragraph]["text"],"voice":voice}

def claim_text(text, attribution, refs, limits):
    return {"text":text,"attribution":attribution,"evidence":refs,"limitations":limits}

def contribution(claim, classification, key=None, novelty="本组原文不支持实质新进展"):
    return {**claim,"classification":classification,"progress_key":key,"change":"new" if key else "none","novelty_basis":novelty,"occurred":{"precision":"unknown"},"reported":{"precision":"unknown"}}

limits=["仅依据两份联合早报已取得的开放正文，不代表完整讨论或独立来源共识。","计划不等于实施；人数、金额及实施细节不在本次归一化主张中。"]
a=claim_text("据联合早报转述，马斯克称将于明年向美国每名儿童赠送SpaceX股份；报道同时指出实施细节尚未提供。","联合早报转述马斯克在X的表态；实施细节限定来自该报道",[reference(9013,1),reference(9013,2)],limits)
b=claim_text("另一篇报道把Anthropic拟设公益基金与马斯克提出的直接分股并置，增加了收益分配方式的比较焦点。","联合早报的报道框架；不是社会讨论转向或共识的判断",[reference(9192,0),reference(9192,1),reference(9192,4)],limits)
positive={"outcome":"ready","reason":"人工写定的mock示例，验证协议与存储，不计真实生成质量","contributions":[contribution(a,"development","musk-announcement","记录原文中的计划表态，不将其写成已实施；日期保守保留unknown"),contribution(b,"discussion_focus","distribution-comparison","相对于本组先前单谈赠股的材料，新增两种收益分配方式比较；只限该材料集合")],"overview":[a,b],"guide":[claim_text("可先读赠股计划的报道，再看两种分配方式的比较；前者保留了尚无实施细节的限定。","本组材料的阅读提示",[reference(9013,2),reference(9192,0)],limits)]}
x=claim_text("书评作者谈到非虚构叙事的主观性，并表示选择尊重作者这一版本的真实。","豆瓣书评作者的读后观点",[reference(9051,4,"author")],["只表示这位作者的观点，不代表读者共识或书中事实已经外部核实。"])
y=claim_text("另一篇作者记录交稿后的多轮修订，并描述阅读结尾时的情绪反应。","豆瓣文章作者的翻译经历自述",[reference(9054,17,"author")],["相对时间和个人体验保留；不足以断言话题出现了新的讨论转折。"])
negative={"outcome":"abstained","reason":"普通观点与翻译背景不足以证明新的讨论焦点，不生成概况/导读","contributions":[contribution(x,"opinion"),contribution(y,"background")],"overview":[],"guide":[]}
calls=[]
def transport(request):
    data=json.loads(request.content)
    packet=json.loads(data["messages"][1]["content"])
    calls.append({"model":data["model"],"review":"draft" in packet,"transport":"httpx.MockTransport"})
    if "draft" in packet:
        out={"checks":[{"target":t,"dimension":d,"supported":True,"reason":"明确mock审核结论；不计真实语义成绩"} for t in packet["targets"] for d in packet["dimensions"]],"issues":[]}
    else:
        out=positive if packet["definition"]["title"]==sets[0]["title"] else negative
    return httpx.Response(200,json={"id":"mock-r207-"+uuid4().hex,"unspun_mock":True,"choices":[{"finish_reason":"stop","message":{"content":json.dumps(out,ensure_ascii=False)}}],"usage":{"cost":0,"prompt_tokens":0,"completion_tokens":0}})

handler=SynthesisHandler({s.id:s for s in sources},scope=scope,allow_mock=True,client_factory=lambda context:LlmClient(context=context,transport=httpx.MockTransport(transport)))
report={"captured_at":datetime.now(UTC).isoformat(),"database":engine.url.database,"artifact":str(artifact.relative_to(ROOT)),"artifact_sha256":hashlib.sha256(artifact.read_bytes()).hexdigest(),"reviewer":reviewer.model_dump(mode="json"),"automatic_membership_used":False,"human_quality_rating":None,"real_model_quality":"unmeasured","sets":[]}
with scope() as s:
    assert not list(s.scalars(select(Article.id))), "Replay requires an empty isolated database; no overwrite"
    seed_packages(s,packages,material_offset=0)
    initialize_budget(s,scope="evaluation")
    policy=s.get(BudgetPolicy,1)
    policy.stage_caps={"topic_synthesis":"0.45","topic_synthesis_review":"0.45"}
    original={aid:fingerprint(qualified_item(s,aid,preview=False,as_of=datetime.now(UTC),sources=sources).content.model_dump(mode="json")) for aid in by_id}

for group in sets:
    topic_id=uuid5(NAMESPACE_URL,"unspun:r207:manual-replay:"+group["key"])
    evidence=[]
    with scope() as s:
        revision=0
        changes=[DefineTopic(kind="issue",title=group["title"],domains=tuple(group["domains"]))]
        for aid,paragraph,relation in group["members"]:
            ref=reference(aid,paragraph,"author" if aid in {9051,9054} else "reported")
            reason="逐条核验主题关联："+group["title"]+"；不扩大为自动归并成果"
            changes.append(SetMember(article_id=aid,material_id=by_id[aid]["material"]["id"],relation=relation,basis=reason,decision_version=MANUAL_VERSION,evidence=(EvidenceRef.model_validate(ref),)))
            evidence.append({"article_id":aid,"material_id":ref["material_id"],"source":by_id[aid]["original_input"]["source_id"],"url":by_id[aid]["article"]["url"],"source_capture":by_id[aid]["origin"],"scope":by_id[aid]["original_input"]["scope"],"original_metadata_times":by_id[aid]["original_input"]["metadata"]["times"],"relation":relation,"reason":reason,"evidence":ref})
        for change in changes:
            receipt=mutate_topic(s,topic_id,TopicMutation(mutation_id=uuid5(topic_id,str(revision)),expected_revision=revision,actor=reviewer.actor,reason=reviewer.basis,change=change),sources=sources,now=datetime.now(UTC))
            revision=receipt.revision
        task=enqueue_synthesis(s,topic_id,revision,reviewer,sources=sources,now=datetime.now(UTC),response_mode="mock")
        assert task==enqueue_synthesis(s,topic_id,revision,reviewer,sources=sources,now=datetime.now(UTC),response_mode="mock")
    for kind in ("topic_synthesize","topic_synthesis_review"):
        with scope() as s:
            lease=claim(s,queue="paid",kinds={kind},worker="r207-explicit-offline-mock",lease_seconds=900)
        if lease is None:continue
        result=handler.run(lease)
        with scope() as s:
            assert complete(s,lease,apply=lambda db:handler.apply(db,lease,result))
    with scope() as s:
        row=s.scalar(select(TopicSynthesis).where(TopicSynthesis.topic_id==str(topic_id)))
        view=read_topic(s,topic_id,sources=sources,now=datetime.now(UTC),contract=text_contract())
        report["sets"].append({"topic_id":str(topic_id),"title":group["title"],"manual_members":evidence,"status":row.status,"response_mode":row.response_mode,"draft":row.draft,"review":row.review,"generation_receipt":row.generation_receipt,"review_receipt":row.review_receipt,"applied":row.applied,"structural_checks":{"updates":[x["check"] for x in view["updates"]],"derivations":[x["check"] for x in view["derivations"]]}})
with scope() as s:
    after={aid:fingerprint(qualified_item(s,aid,preview=False,as_of=datetime.now(UTC),sources=sources).content.model_dump(mode="json")) for aid in by_id}
    assert after==original
    report.update(independent_cards_preserved=original,mock_responses=len(calls),mock_calls=calls,generation=0,embedding=0,paid_retries=0,provider_queries=0,model_response_transport="httpx.MockTransport only",synthetic_journal_cost_usd="0",original_ledger_access=False,production_access=False)
(ROOT/"docs/acceptance/r2-07/manual-replay.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
print(json.dumps({"states":[x["status"] for x in report["sets"]],"mock_responses":len(calls),"real_calls":0,"original_cards_preserved":len(original)}))
