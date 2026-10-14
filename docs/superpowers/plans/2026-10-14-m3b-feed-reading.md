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

- [ ] 用户核实成员/来源/时间、补充漏失领域与真实边界例、标注重要性和“值得读”、确认媒体分组并写出三种排序的明确优先关系。
- [ ] 冻结样本版本、快照哈希、标注哈希与审阅者；同批比较旧基线及候选。全部硬性回归与人工明确排序对通过，再接入 CI。缺少标注时保留未就绪结论。

## Task 5 · B1 正式查询（Task 4 通过后）

文件：`core/feed_ranking.py`、`api/events.py`、`core/params.py`、排名配置、`tests/test_feed_ranking.py`/`test_events_api.py`、`web/src/FeedPage.tsx`/`EventCard.tsx`/`api.ts` 和筛选测试。

- [ ] 先写数据库集成失败测试，移植已通过离线对照的时间聚合 SQL；默认 newest/7d，复合键游标携带 as_of/条件/版本，按ID决胜。限制游标长度和值域；新文章 fetched>as_of 不影响后续页。
- [ ] 正式 hot 参数仅取冻结评测版本；important 复用 score_final。未过人工门槛不得用占位热度替代。
- [ ] 写前端失败测试后加入三种排序/四个独立范围，窗口说明、加载更多与报道时间/系统时间分离。
- [ ] 跑全套数据库/静态/前端检查，启动隔离模拟数据预览；用户体验验收后才提 B1 PR。

## Task 6 · B2 阅读与偏好（B1 合并后）

文件：增量迁移 `000009`（按当时主线实际 head 递增）、`core/models.py`、独立状态/偏好 API 及数据库测试、前端读取/写入/恢复模块及测试。

- [ ] 数据库失败测试后加入事件状态和单行偏好；版本条件更新，竞争409，缺事件404，未知身份/跨站写入拒绝。API复用Access验证。
- [ ] 未读在服务端分页前筛选。只有显式按钮改变已读，新增报道不撤销已读。
- [ ] 前端失败测试后实现 URL > 服务端 > 离线本地回退 > 默认优先级、选择保存、冲突提示、成功后缓存更新、断网禁写、标签返回同步。
- [ ] 全套检查、390/400px和键盘/主题/双浏览器同步预览；用户体验通过再提B2 PR，不将B1/B2准备勾为完成。

## 本批验证与交付

- [x] `uv run ruff check .`、`uv run ruff format --check .`、`uv run pyright`、隔离迁移库 `uv run pytest -q`。
- [x] 检查 JSON/文档链接、快照与标注哈希、CLI退出码、敏感字段未导出和git diff；提交本批准备，不宣称B1/B2交付。

本计划沿用已批准方案1；本批先完成必要的可执行评测准备。不是改选“先交付最新事件与阅读”的方案2。正式 API/页面和热度公式激活继续受 Task 4 门槛约束。

实施记录（2026-10-14）：Task 1–3 已实现；40 个生产事件候选、53 篇文章、45 项新增回归检查。草稿实际返回0但保持不通过；严格模式实际返回1，327项未就绪信息均保留。独立代码审查发现并修复候选调参污染历史基线的问题；冻结标签同时绑定快照、候选参数与源码。Task 4 人工标注仍待完成，Task 5–6 尚未开工。

最终验证：按项目要求从 `server/` 运行，隔离 `unspun_m3b_test` 迁移至000008，480项后端测试通过、Ruff/格式与严格Pyright通过；独立审查确认修正后的45项新增检查通过。一次从仓库根目录误运行全套测试时因既有相对配置/迁移路径失败，随后使用规定目录重新运行并通过；未为该命令问题修改产品代码。前端无变更，未进行页面交付或体验验收。
