# M3-B · 排序离线评测准备

当前状态（2026-10-14）：40项用户重要性及阅读判断原样保留，53篇原文技术核实已完成；[冻结评估](frozen-ranking-report.json)严格通过。重要优先满足火车事故3509先于WorkBuddy4029；黎曼/太阳能不设强制排名。正式B1查询与页面正在实施，页面体验验收后才开PR；生产尚未更新。下方早期草稿及未就绪记录作为历史证据保留，以本段和[最新评估说明](current-evaluation.md)为准。

`production-candidates.json` 是 2026-10-14 05:53:46 UTC 的生产只读快照。生产有 5131 个事件，按现有综合分四分位各选10个确定性候选，合计40个事件、53篇成员报道；保留全部成员的时间与原文链接，没有截断事件成员，没有模型调用或生产写入。旧基线半衰期24h已从生产worker配置只读核实；配置读取晚于数据库快照，并非同一原子快照，证据时序保存在输入中。该抽样不保证领域和特殊案例覆盖，用户可替换候选，最终保持30–50个真实事件。已有开发库“1132篇文章、0事件”的旧观察仍成立，它和本次生产快照不是同一数据集。

## 文件

- [人工审阅表](review-sheet.md)：事件概览、原文链接、待填判断、机器时间建议；历史分数/摘要与人工栏分开。可以编辑Markdown或在对话中逐批给判断。
- [标注输入](annotations.json)：40个事件的重要性分已按用户填写的审阅表同步；“现在是否值得读”也已按用户填写同步（32是/8否），事件2215重要性已修订为1。技术字段仍待核实，未冻结，不能成为通过样本。
- [快照](production-candidates.json)：输入固定时刻、既有分数、系统时间、文章元数据及抽样信息。
- [草稿报告](draft-report.json)：离线输出，仅草稿；含三种候选、旧版changed_at衰减基线和不带增长奖励的活动对照。全部/today/24h/7d分别保存，旧版基线始终是原有无范围筛选的完整列表。
- [严格就绪报告](strict-readiness-report.json)：实际严格执行拒绝了未标注集；`ready=false, passed=false`，不是评测通过。

所有文章标题/原文来自真实采集，摘要和既有分数是历史模型产物，不是本轮人工事实或重要性验证。不同来源ID、不同域名都不自动等于独立媒体或独立证据。来源分组缺失时草稿暂用source_id，报告明确为 `draft-unverified`。只有人工确认媒体分组后才可形成正式评测。

## 人工需要补充的内容

1. 保留已完成的40项重要性及阅读判断；技术字段由[集中核实清单](verification-packet.md)提供建议供集中审阅：领域、每篇文章时间分类、出版方分组、转载核实状态。聚合入口用 `article_publisher_groups` 按文章覆盖，同媒体直接来源仍可用 `publisher_groups` 默认；用户无需再逐项填写技术字段。未知转载允许保留未知；空关系数组不等于已证明没有转载。
2. 事件及整体审阅者、带时区的审阅时间。至少三个领域，整体覆盖说明须明确记录哪些边界仍由合成回归覆盖、哪些已有真实案例。聚类错误、缺少原文或覆盖不足的候选应替换。
3. 三种排序分别给出明确优先事件对：`sort/range/before_event_id/after_event_id/reason/reviewed_by/reviewed_at`。允许无偏好的事件不参加对比，不能编造总排名。事件对都必须在对应候选窗口中，否则保留失败。
4. 核实的时间分类与规则候选不一致时，评测拒绝通过，需解决规则或原始输入问题，不擅自忽略人工意见。
5. 填妥后冻结版本及快照、标注、候选参数、候选源码哈希；任何标签/关系/排序对再修改都需要重新审阅冻结。哈希记录审阅输入的完整性，不能验证审阅身份；不凭文件中填了名字就声称作者身份已验证。

重要性/“值得读”用于保留人工判断和评分标准准备；当前排序正确性以人工明确优先关系验证，不声称通过少量事件对就证明总体排名准确率。所有时间与热度硬规则同时由纯函数回归测试覆盖。

## 2026-10-14 人工评分与时效性反馈

用户已填写40项重要性分并确认：时效性新闻应检查当前价值，长期知识允许保留但需仍适用。分数原样导入，未推断用户打分动机；`worth_reading` 单独表示本轮参照日期的“现在是否值得读”。内容类型、当前有效性和依据先记审阅表备注，M3-D0设计机器字段时再接入；本轮不增加付费分类或修改线上采集/排序。参见D-020与需求“内容时效与当前阅读价值”。

最初 `draft-report.json` / `strict-readiness-report.json` 保留为全未标注阶段证据，其标注哈希对应当时输入；评分导入后的当前报告为 `importance-draft-report.json` / `importance-readiness-report.json`，不能混用旧报告声称新标签已通过。

## 运行

在 `server/`：

```sh
uv run python -m unspun.evaluation.run_feed_ranking \
  --snapshot ../docs/evaluations/m3b/production-candidates.json \
  --annotations ../docs/evaluations/m3b/annotations.json \
  --output ../docs/evaluations/m3b/reading-draft-report.json --draft
```

`--draft` 返回0方便审阅，但强制 `passed=false`。去掉 `--draft` 是严格检查：未就绪/排名对失败返回1，输入无法读取返回2，通过才返回0。输出不能覆盖快照或标注输入。该命令离线执行，不连接数据库、网络或模型。

人工输入完成并明确获准冻结后，记录哈希（不会填补人工字段）：

```sh
uv run python - <<'PY'
import json
from pathlib import Path
from dataclasses import asdict
from unspun.evaluation.feed_ranking import DEFAULT_PARAMS
from unspun.evaluation.feed_suite import candidate_source_hash, content_hash
path = Path('../docs/evaluations/m3b/annotations.json')
doc = json.loads(path.read_text())
doc['parameters_sha256'] = content_hash(asdict(DEFAULT_PARAMS))
doc['candidate_source_sha256'] = candidate_source_hash()
doc['frozen'] = True
doc['frozen_sha256'] = content_hash({k: v for k, v in doc.items() if k != 'frozen_sha256'})
path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
PY
```

严格运行应使用另一个报告路径，保留草稿和失败结果；不要以最后一次成功覆盖之前的失败证据。

## CI 与正式实施门槛

本批新增pytest会在现有CI后端测试任务中执行，验证时间规则和评测就绪检查。实际人工集仍未标注，当前不把失败的draft接到所有无关PR。B1正式排名激活PR必须新增严格命令CI步骤（去掉 `--draft`），通过人工就绪和明确排名关系检查后才可合并；不允许通过只运行合成测试绕过此门槛。

冻结后新增媒体分组和排名参数只用于B1查询，不改旧LLM评分，也不回写历史日报。B2按已批准设计在B1合并基线上实施。详见[设计](../../superpowers/specs/2026-10-14-m3b-feed-reading-design.md)和[计划](../../superpowers/plans/2026-10-14-m3b-feed-reading.md)。

## 阅读判断导入与技术核查（2026-10-14）

32项是、8项否已原样同步，熊猫回国事件重要性2→1修订。新一轮输入版本为`m3b-human-review-v2`；本轮输出使用`reading-draft-report.json` / `reading-readiness-report.json`，以前的重要性阶段报告保留历史证据。

`proposed-review.json`只保存AI辅助领域/原文域名分组及三对排序建议，不注入人工审阅字段。`origin-verification.json`记录8个原文尝试、7个可读结果及日期差异；Nature身份重定向失败保留未核实。原始快照不改。时间字段通过格式规则不能证明是原文首次发布时间；HN/论文公告日期与原文日期不符，3125和2113还有成员边界疑点，须保留为核查/失败案例，不能偷偷删成员或继承拆分后评分。

离线工具已修正聚合入口分组：`article_publisher_groups`以文章ID为键，优先于来源默认分组；严格检查成员归属与完整覆盖。日期、媒体建议和排序关系仍未确认，无法冻结/通过，不影响线上API或生产数据。

## 排序偏好进一步反馈（2026-10-14）

用户要求火车事故3509在WorkBuddy4029前，依据是伤亡与关注价值；重要优先还是当前热度适用范围已提出澄清。两种现有候选均给相反顺序，完整比较保存在`priority-feedback.json`。不猜测媒体实际关注量、不用死亡关键词特判。用户接受黎曼猜想4612与太阳能138的任意顺序，委托AI决定；该旧建议已撤回强制性，暂沿用现有综合分，不伪造人工硬期望。技术字段/样本冻结状态保持待核实。
