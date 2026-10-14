# M3-B · 排序离线评测准备

状态：待人工标注，未通过评测；不改变线上事件流、存储评分、聚类或日报。

`production-candidates.json` 是 2026-10-14 05:53:46 UTC 的生产只读快照。生产有 5131 个事件，按现有综合分四分位各选10个确定性候选，合计40个事件、53篇成员报道；保留全部成员的时间与原文链接，没有截断事件成员，没有模型调用或生产写入。旧基线半衰期24h已从生产worker配置只读核实；配置读取晚于数据库快照，并非同一原子快照，证据时序保存在输入中。该抽样不保证领域和特殊案例覆盖，用户可替换候选，最终保持30–50个真实事件。已有开发库“1132篇文章、0事件”的旧观察仍成立，它和本次生产快照不是同一数据集。

## 文件

- [人工审阅表](review-sheet.md)：事件概览、原文链接、待填判断、机器时间建议；历史分数/摘要与人工栏分开。可以编辑Markdown或在对话中逐批给判断。
- [标注输入](annotations.json)：40个事件的所有人工字段为空，媒体映射也未推断；未冻结，不能成为通过样本。
- [快照](production-candidates.json)：输入固定时刻、既有分数、系统时间、文章元数据及抽样信息。
- [草稿报告](draft-report.json)：离线输出，仅草稿；含三种候选、旧版changed_at衰减基线和不带增长奖励的活动对照。全部/today/24h/7d分别保存，旧版基线始终是原有无范围筛选的完整列表。
- [严格就绪报告](strict-readiness-report.json)：实际严格执行拒绝了未标注集；`ready=false, passed=false`，不是评测通过。

所有文章标题/原文来自真实采集，摘要和既有分数是历史模型产物，不是本轮人工事实或重要性验证。不同来源ID、不同域名都不自动等于独立媒体或独立证据。来源分组缺失时草稿暂用source_id，报告明确为 `draft-unverified`。只有人工确认媒体分组后才可形成正式评测。

## 人工需要补充的内容

1. 每个事件的领域、重要性1–5、“值得读”布尔值、每篇文章时间分类、每个来源的媒体分组、转载关系已审阅标志。未知转载允许保留未知；空关系数组不等于已证明没有转载。
2. 事件及整体审阅者、带时区的审阅时间。至少三个领域，整体覆盖说明须明确记录哪些边界仍由合成回归覆盖、哪些已有真实案例。聚类错误、缺少原文或覆盖不足的候选应替换。
3. 三种排序分别给出明确优先事件对：`sort/range/before_event_id/after_event_id/reason/reviewed_by/reviewed_at`。允许无偏好的事件不参加对比，不能编造总排名。事件对都必须在对应候选窗口中，否则保留失败。
4. 核实的时间分类与规则候选不一致时，评测拒绝通过，需解决规则或原始输入问题，不擅自忽略人工意见。
5. 填妥后冻结版本及快照、标注、候选参数、候选源码哈希；任何标签/关系/排序对再修改都需要重新审阅冻结。哈希记录审阅输入的完整性，不能验证审阅身份；不凭文件中填了名字就声称作者身份已验证。

重要性/“值得读”用于保留人工判断和评分标准准备；当前排序正确性以人工明确优先关系验证，不声称通过少量事件对就证明总体排名准确率。所有时间与热度硬规则同时由纯函数回归测试覆盖。

## 运行

在 `server/`：

```sh
uv run python -m unspun.evaluation.run_feed_ranking \
  --snapshot ../docs/evaluations/m3b/production-candidates.json \
  --annotations ../docs/evaluations/m3b/annotations.json \
  --output ../docs/evaluations/m3b/draft-report.json --draft
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
