# M3-B Feed Ranking and Reading Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans task-by-task; dependent evaluation gates remain sequential. Apply test-driven-development and verification-before-completion. Checkboxes track evidence rather than intent.

**Goal:** 先使已批准的 M3-B 设计具有真实候选、可执行时间/排序对照与人工评测门槛，再按 B1 → B2 实施正式 API 和页面。

**Architecture:** 第一批只读快照与纯离线评测代码放在 `unspun.evaluation`；不由正式事件 API 引用，不改变线上排序。冻结人工事件集且候选评测通过后，B1 将已验证规则移入数据库查询层；B2 在 B1 合并基线上新增单用户数据库状态及前端操作。

**Tech Stack:** Python、Pydantic、pytest、SQLAlchemy/Postgres；后续 FastAPI、React、TanStack Query、Vitest。

## Task 1 · 真实事件候选与人工标注材料（本批）

文件：`docs/evaluations/m3b/production-candidates.json`、`annotations.json`、`README.md`、`review-sheet.md`。

- [x] 用 `BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY` 只读抽取生产事件及全量成员文章元数据。按原有分数四分位各取 10 个确定性候选，不调用模型。
- [x] 保存快照哈希，生成 40 个未标注记录（所有人工分值、判断、媒体分组和审阅身份均空），生成带原文链接的中文审阅表。
- [x] 核验事件 ID 唯一、成员文章 ID 唯一、原文 http(s)、快照数量与来源。声明按分数抽样不能代表所有领域，必须由用户审阅覆盖。

## Task 2 · 离线时间契约与排序对照（本批）

文件：`server/src/unspun/evaluation/feed_ranking.py`、`server/tests/test_feed_ranking_evaluation.py`。

- [x] 写失败测试：2025 报道/2026 入库、未来超过 5 分钟、缺失日期、未来抓取排除、补早报道、新增晚转载、北京时间边界、同媒体多栏目/重复、新旧分数排名差异、同分 ID 决胜。

```python
assert report_times(old_event, as_of).earliest == old_published_at
assert rank_events([old_event, fresh_event], "newest", "all", as_of)[0].id == fresh_event.id
```

- [x] 运行 `uv run pytest tests/test_feed_ranking_evaluation.py -q`，确认因模块/行为缺失失败。
- [x] 实现纯函数：`report_times`、`window_start`、`rank_events`。使用 UTC aware datetime，epoch 下限与抓取 +5min 规则；窗口为 `[start, as_of]`；未知时间仅全部末尾。候选热度用窗口内每媒体最早时间、24h 衰减、6h 新媒体活动奖励 0.5；对照包括原 changed_at 衰减和无增长奖励的活动。
- [x] 运行同组测试至通过；公式只进入离线候选，不接正式 API。

## Task 3 · 严格人工就绪检查和报告 CLI（本批）

文件：`server/src/unspun/evaluation/feed_suite.py`、`run_feed_ranking.py`、`server/tests/test_feed_suite.py`。

- [x] 写失败测试：样本少于30或超过50、假生产标识、重复事件/文章、缺少人工值、未审阅媒体分组、同来源分组冲突、无时区审阅时间、快照哈希不符、未冻结、缺排序对、排序对引用不存在事件、错误的候选排名不得过关。

```python
report = evaluate_suite(snapshot, draft_annotations)
assert report["ready"] is False
assert report["passed"] is False
```

- [x] 运行 `uv run pytest tests/test_feed_suite.py -q` 确认缺少行为失败。
- [x] 实现输入 schema 与 `evaluate_suite`；人工标签不得有自动默认值。报告保存快照/标注/参数/源码哈希、候选排序及旧基线，明确缺失门槛和违反的排序对。通过须满足人工就绪、冻结有效与全部明确排序关系。
- [x] 实现 `uv run python -m unspun.evaluation.run_feed_ranking --snapshot PATH --annotations PATH --output PATH`，默认未就绪/不通过返回非零；`--draft` 仅供审阅输出并返回0，仍保持 `passed=false`。
- [x] 明确 CI 接入命令：上述严格命令；当前 draft 不接到所有 PR 阻断已有开发，B1 排名激活 PR 必须接入严格命令且通过。
- [x] 用真实40事件产生 draft 报告；再运行严格模式确认实际拒绝未标注集。

## Task 4 · 评测门槛（人工依赖）

- [x] 用户完成40项主观判断并授权AI技术核查；53篇原文时间/媒体分组、混主题负例及三种排序契约分别记录审阅身份。
- [x] 冻结40例、输入/参数/代码哈希与审阅者；严格评估通过，重要火车优先约束和最新/热点技术契约通过，CI已接入严格命令；历史失败记录保留。

## Task 5 · B1 正式查询（Task 4 通过后）

文件：`core/feed_ranking.py`、`api/events.py`、`core/params.py`、排名配置、`tests/test_feed_ranking.py`/`test_events_api.py`、`web/src/FeedPage.tsx`/`EventCard.tsx`/`api.ts` 和筛选测试。

- [x] PostgreSQL查询移植已通过规则，默认newest/7d、复合键分页与版本条件；真实40例的3×4 SQL/离线排名完全一致。
- [x] 正式hot使用冻结24h/6h/0.5；important加已通过的48h原文依据急迫优先层，原score_final保留。
- [x] 前端TDD加入三种排序/四个范围、URL恢复、分页和日期精度/系统时间分离，定时刷新重开第一页。
- [x] 后端592/前端77项测试、Ruff/Pyright/前端lint/typecheck/build通过；独立固定时刻预览、390/400px亮暗色及分页/历史恢复检查通过；用户明确体验验收通过并要求提PR。

## Task 6 · B2 偏好恢复（2026-10-15按D-021修订）

用户取消已读/未读及只看未读，B2只保留排序/时间范围恢复；旧阅读状态实现已撤销，不用自动标记替代。

- [x] 000010仅创建单行偏好表；复用Access和同源验证，版本条件更新、首次写入竞争409。
- [x] URL > 服务端 > 服务端不可达时本机最后同步偏好 > 默认值；显式链接不自动写入，操作控件才保存，冲突提示后用新版本重试。
- [x] 删除阅读状态表定义、read-state API、未读查询、卡片按钮；旧unread_only链接不隐藏事件。
- [x] 新建隔离数据库全量迁移、597项后端、82项前端、静态检查/构建和迁移一致性通过。
- [x] 用户重启并体验修订版后回复“ok”，D-012验收通过，可提PR；详见[B2预览](../../evaluations/m3b/b2-preview-acceptance.md)。

## 本批验证与交付

- [x] `uv run ruff check .`、`uv run ruff format --check .`、`uv run pyright`、隔离迁移库 `uv run pytest -q`。
- [x] 检查 JSON/文档链接、快照与标注哈希、CLI退出码、敏感字段未导出和git diff；提交本批准备，不宣称B1/B2交付。

本计划沿用已批准方案1；本批先完成必要的可执行评测准备。不是改选“先交付最新事件与阅读”的方案2。正式 API/页面和热度公式激活继续受 Task 4 门槛约束。

实施记录（2026-10-14）：Task 1–3 已实现；40 个生产事件候选、53 篇文章、45 项新增回归检查。草稿实际返回0但保持不通过；严格模式实际返回1，327项未就绪信息均保留。独立代码审查发现并修复候选调参污染历史基线的问题；冻结标签同时绑定快照、候选参数与源码。Task 4 人工标注仍待完成，Task 5–6 尚未开工。

最终验证：按项目要求从 `server/` 运行，隔离 `unspun_m3b_test` 迁移至000008，480项后端测试通过、Ruff/格式与严格Pyright通过；独立审查确认修正后的45项新增检查通过。一次从仓库根目录误运行全套测试时因既有相对配置/迁移路径失败，随后使用规定目录重新运行并通过；未为该命令问题修改产品代码。前端无变更，未进行页面交付或体验验收。

用户反馈进展（2026-10-14）：40项人工重要性已完成并原样同步；其他人工栏目仍待填。D-020补充内容类型/当前有效性与付费前筛查，具体规则归D0/D1/D2，不改变本计划B1/B2顺序。旧新闻与长期知识保留作边界样本，不自动降重要性或补“现在值得读”；后续固定准入字段时再扩展schema。本轮仅更新需求与标签记录，不接正式过滤或付费分类。

阅读反馈进展（2026-10-14）：40项阅读判断导入，事件2215分值修订保留；准备集中技术核实与三对排序建议，未伪造确认。RSS入口不能一对一代表出版方，离线分组按文章覆盖（4项新增回归）；8个原文抽查保留7可读/1不可读，确认部分公告/讨论日期晚于原文公开日期与混聚类边界。正式B1需先明确时间依据和验证成员；评分相反的排序对保持待确认，不靠改期望通过。

本轮验证：聚合入口修正经独立审查通过，49项离线回归、独立数据库全量484项、Ruff/格式与严格Pyright均通过。reading草稿返回0但ready/passed均false；严格模式返回1，保留260项待核实信息。网页核查仅将7个可读结果作为技术证据，未核实项不填人工字段；已向用户提出三组具体排序关系的核实请求。

## 本轮实施补充（用户已明确“那你开始吧”）

用户授权AI负责技术核查，采用“重要优先体现伤亡与公共影响、热度保持报道活动”口径；黎曼/太阳能不设硬顺序。主观列仍仅使用用户实际填写值；领域、出版方和时间核查注明AI技术审阅，不伪装成人工评分。

1. 并行核查全部53个原文，保存可访问/不可访问、精确时刻/仅日期、转载与时间依据。原始生产快照保留，候选输入另存经核查的技术版本；未知仍为未知，日期不补午夜，混聚类标为边界负例并保留全部成员。
2. TDD实现 `core/publication.py`：HTML原始发布日期提取及时间精度；有时区日期转UTC，无时区/仅日期保留日期，修改日期/讨论日期不能冒充发布。日期不确定区间采用全部合法时区的保守范围并截断至已抓取/查询时刻；排序内部下界与用户可见报道时刻分开。HTML内容和URL为不受信输入，不下载额外脚本或执行网页内容。
3. TDD实现 `core/public_impact.py`：依据可追溯原文判断近期急迫的生命健康、基本服务风险/紧急保护行动；常规产品、长期研究、历史回顾不自动升为急迫。模型输出引用绑定成员文章、匹配原文；无法核实/预算不足保留未知。重要优先仅对最早已知报道保守下界距as_of不超过48h的可支持急迫事件优先，同档仍按旧综合分；转载不延长期限。48h是固定待评测候选参数，不把“死亡”关键词或事件ID写进排序。
4. 离线标准集保留40项主观评分，加入用户明确的重要优先3509→4029、已批准时间/来源活动契约的技术回归，不强制4612/138顺序。技术审阅与主观作者分别记录；冻结输入/参数/模型/提示/代码哈希后对照旧基线，失败保留。40个真实候选及明确的合成边界控件分开，不以合成通过冒充人工质量评测。
5. 真实模型对照只在独立本地评测库运行、记录全部费用，沿用flash档及0.40滚动审核预算；单轮最多60次、$0.15停止后续调用，不改生产数据或获取原始密钥到文件/日志。新公共影响元数据不回写旧综合分或日报；正式接入必须先通过冻结集/CI。
6. 门槛通过后TDD接正式查询/前端并按D-012启动独立预览。B2仍在B1交付基线上推进；生产历史补查/聚类纠正不绕过C2受控流程。

### 实测后的有限重试（2026-10-14）
第一轮误用了 summary_model（Flash Lite），46 次调用耗费 $0.0044285；其中非紧急对照出现格式失败，结果保留且不算通过。澄清 JSON 对象格式后，以原计划 Flash 模型进行一次完整的 46 案例重跑。两轮累计调用上限调整为 110（含底层截断重试），累计费用仍不得超过 $0.15，共享 grounding $0.40/24h 限额不变；不允许无限调参/选择性删除失败案例。

用户页面验收（2026-10-14）：明确回复“验收通过，快速提PR”。已通过D-012，不再重复请求许可；完成最后已发现问题的验证后直接创建B1 PR。

B2实施记录（2026-10-15）：主线B1已合并（#54），在 `feat/m3b-b2-reading` 实现000010、单用户状态和偏好CAS写入、Access身份和同源验证、服务端未读分页及前端恢复/冲突/断网处理。后端接口先验证缺模块失败再实现；前端沿用B1测试改造并补充行为回归，不宣称前端每条新增测试均先红后绿。隔离数据库597项、前端83项、静态检查/构建及迁移一致性/冻结排名评估通过。用户体验门槛仍待确认，详见[B2预览记录](../../evaluations/m3b/b2-preview-acceptance.md)，未勾选整体完成、未创建PR或部署。

2026-10-15用户体验修订：明确认为读过的事件从流中移除不合理，确认采用D-021。上述旧B2记录及597/83测试数量仅为修订前历史证据；当前以Task6和B2预览为准。未合并部署的000010仅保留偏好表；旧本地演示库保留，另建空库验证，无生产数据操作。
