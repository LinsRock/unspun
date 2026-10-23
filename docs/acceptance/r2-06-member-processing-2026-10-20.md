# R2-06 第一批 · 关闭的成员处理链

本批只交付候选/成员判断的工程处理链、共享队列和账务；**R2-06 整体未完成**。真实模型精度与覆盖、后台最小纠错和生产启用留下一批。R2-04 观察容器、只读挂载、worktree 及原件保留，不接手启源；R2-07+、清理和 R3 未实施。

基线 `ed86474c904ac136e3d933c7c736f18de3d7902b`，分支 `feat/r2-member-processing`，独立目录 `/Users/li.cong/.config/superpowers/worktrees/unspun/r2-member-processing` 与独立 venv。[实际导入](https://github.com/LinsRock/unspun/blob/eb5b19f749c8316174e9cc5f6e838d7bbb0aec85/docs/acceptance/r2-06/import-check.json)指向本轮 89 个源码；共享 editable、原观察挂载均未改。[处理/费用契约](../superpowers/specs/2026-10-20-r2-06-member-processing.md)固定范围和下一批缺口。

## 处理与费用契约

显式内部入口按当前合格 R1 规范内容排 `topic_recall → topic_judge → topic_review`，共用 paid 队列、原单槽消费者及 object/lease/claim fencing。阅读、调度及原卡片链不自动排新任务。领域限定最多 32 个现有话题，每话题最多两个有效材料锚点，主体主题词与原发时间排序后最多 12 个话题按需 embedding，再最多 4 个判断候选。未知时间及长背景保留路径；不声称完整召回。空候选不建话题。

`content_vectors` 追加版本键覆盖规范身份/别名、当前材料实际输入、来源边界、合格 card/审核版本、输入文本/截断契约、模型/维度。旧 Article.embedding/Event.centroid 不参与复用。checkpoint 校验租约与当前输入；重启读取已提交向量和统一账本已知响应。候选和任务指纹覆盖话题 revision/定义、所选成员 revision/输入、向量版本及判断/审核契约。相似度不进入语义判定或写入条件。

判断区分 same_event、same_issue、background、opinion、explanation、reprint 和 independent，uncertain 始终独立；关联须同时有本材料及候选锚点的原文引用。独立审核须明确批准同一判断指纹且 issues 为空。审核后再次锁话题，校验输入/契约/来源、revision 和租约，才经 R2-05 CAS 写成员；冲突保留 stale，已有成员/移除记录不自动覆盖或复活。原独立阅读、card/guide 及话题派生失效规则保持。

三个新费用阶段为 `topic_embedding/embed`、`topic_judgment/judge` 和 `topic_review/review`，仍写原 BilledRequest/LlmUsage 并关联 task/attempt/article/source/object；审核用 grounding，受原生产 `$0.40/24h` 附加上限。阶段/用途/模型/租约必须匹配，不能借 legacy/card/自动 embedding 分类绕过。物理重试逐笔记账，unknown 保留完整预留，租约过期不释放费用。

生产/评测未显式分配新阶段即拒绝；生产还要求 legacy=0、各阶段分配和 ≤原 `$13.50`。登记的下一批方案为 card=9.50、guide=2、embedding=1、新三阶段分别 0.10/0.45/0.45，合计 `$13.50`。**代码不自动写旧政策，本批未应用此方案**；原项目 `$15`、原累计评测 `$1.50`、模型及原来源/配额保持。新开关 `r2_member_processing_enabled=false`，无自动 producer；本批新增付费请求/实付 **0 / $0**。

## 验证、恢复和审查

新建 `unspun_r206_tests_20261020` 跑 982 项基线；首次新夹具 teardown 缺少解除材料引用而失败，保留原库/日志。修正夹具后在新建 `unspun_r206_tests_v2_20261020` 到 `000019` 完成 **1,020 项、0 跳过**。其中新链 **38 项**含双连接排队/领取幂等、两个审核者对同一 revision 的 CAS 竞争（一 applied、一 stale）、领取过期/晚返回、全新 Python 进程复用、材料/身份/来源/候选/契约变化、多话题及移除保护、预算延期、物理重试、未知费用和旧分类绕过拒绝。模型和测试外部 HTTP 全部 mock，费用数字是隔离合成账本。

Ruff/format、Pyright（0 错误）、Alembic check 无漂移；部署 18 项和 CI 范围 11 项及原 subtests 通过。原排序 40 案例结果与 R2-04 报告字节相同；[冻结核验](r2-06/freeze-validation.json)27/27 和 52 份原配置/材料保持，[冻结输入回放](https://github.com/LinsRock/unspun/blob/eb5b19f749c8316174e9cc5f6e838d7bbb0aec85/docs/acceptance/r2-06/frozen-replay.json)为相同 20 回归/10 留出及原公开集合/推荐/最新分值，仅验证工程契约和默认关闭，不调参、补评分或声称真实归并通过。真实精度/覆盖为 null。[完整验证](r2-06/validation.json)保留命令结果及日志散列。

[恢复演练](https://github.com/LinsRock/unspun/blob/eb5b19f749c8316174e9cc5f6e838d7bbb0aec85/docs/acceptance/r2-06/recovery.json)在新建 `unspun_r206_recovery_v2_20261020` 以 `000018` 种旧业务/账务/unknown 预留与已有话题，升级不改旧表散列和序列，再用 mock 完成向量、判断、审核/CAS 及成员移除历史。完整 dump→新建 `unspun_r206_restored_v2_20261020` 后，所有表计数/散列/序列及话题历史、向量/审核版本一致；重复升级成功，downgrade 报错且全部数据保留。首个空库演练的路径错误、首次测试失败和后续修正见[失败登记](https://github.com/LinsRock/unspun/blob/eb5b19f749c8316174e9cc5f6e838d7bbb0aec85/docs/acceptance/r2-06/failures.json)。

[实际生产备份隔离恢复](https://github.com/LinsRock/unspun/blob/eb5b19f749c8316174e9cc5f6e838d7bbb0aec85/docs/acceptance/r2-06/production-restore.json)从生产只读 pg_dump，完整备份留在私有缓存；恢复到新建 `unspun_r206_prod_restore_20261020` 后升级，33 张旧表计数/散列、113 个合格详情及推荐/最新前两页保持，两张新表为空。生产未执行恢复/降级。[资源清单](https://github.com/LinsRock/unspun/blob/eb5b19f749c8316174e9cc5f6e838d7bbb0aec85/docs/acceptance/r2-06/retained-resources.json)保留全部八个隔离库、两份成功备份、测试镜像及 worktree。[固定镜像验证](https://github.com/LinsRock/unspun/blob/eb5b19f749c8316174e9cc5f6e838d7bbb0aec85/docs/acceptance/r2-06/fixed-image-compatibility.json)只承诺本批 `000019` 镜像；上批固定 `000018` 镜像不能解析新 revision，迁移失败关闭且恢复库全部行/schema 保留。回退用认识 `000019` 的固定镜像及退役后的部署文件；需原 schema 时恢复到独立库/卷，保留新库和核对写入差额，不 stamp/删历史造兼容。

审查覆盖最终差异及 R2-05 校验、现有 canonical/material/qualification、R1 runtime/队列、账本/费用查询、只读阅读与部署调用方。新增任务不会被默认 runtime 领取；新费用阶段默认无分配，旧政策/模型/排序及退役 worker 保持。补强了实际阶段/模型匹配、受限语义输入投影及最终 CAS 前的租约复验；完整回归与固定镜像对应最终源码。

## 发布与下一批

部署前 [运行](https://github.com/LinsRock/unspun/blob/eb5b19f749c8316174e9cc5f6e838d7bbb0aec85/docs/acceptance/r2-06/predeploy-runtime.json)、[阅读](https://github.com/LinsRock/unspun/blob/eb5b19f749c8316174e9cc5f6e838d7bbb0aec85/docs/acceptance/r2-06/predeploy-reading.json)、[生产账务](https://github.com/LinsRock/unspun/blob/eb5b19f749c8316174e9cc5f6e838d7bbb0aec85/docs/acceptance/r2-06/predeploy-production.json)、[原评测](r2-06/predeploy-evaluation.json)、[旧业务](https://github.com/LinsRock/unspun/blob/eb5b19f749c8316174e9cc5f6e838d7bbb0aec85/docs/acceptance/r2-06/predeploy-protected-production.json)、[worker 边界](https://github.com/LinsRock/unspun/blob/eb5b19f749c8316174e9cc5f6e838d7bbb0aec85/docs/acceptance/r2-06/predeploy-boundaries.json)、[观察环境/原件](https://github.com/LinsRock/unspun/blob/eb5b19f749c8316174e9cc5f6e838d7bbb0aec85/docs/acceptance/r2-06/predeploy-observation.json)和[关闭链路](https://github.com/LinsRock/unspun/blob/eb5b19f749c8316174e9cc5f6e838d7bbb0aec85/docs/acceptance/r2-06/predeploy-member-chain.json)均为带时间只读截面。原观察 worktree [保护核验](https://github.com/LinsRock/unspun/blob/eb5b19f749c8316174e9cc5f6e838d7bbb0aec85/docs/acceptance/r2-06/protected-r204-worktree.json)仍是干净 `b5f812c`。[PR #116](https://github.com/LinsRock/unspun/pull/116) 于 `2026-10-20 09:38:56 UTC` 合并为 **`78061d7bb6731fd8002807b0b8247dc8301901e0`**（实现头 `d0b25fb`）。[PR CI](https://github.com/LinsRock/unspun/actions/runs/39401842726) 和[主干 CI/实际发布](https://github.com/LinsRock/unspun/actions/runs/39402219835) 均成功，后端、前端 lint/TypeScript/Vitest/build/PWA 与 required-checks 全部通过。[发布步骤](https://github.com/LinsRock/unspun/blob/eb5b19f749c8316174e9cc5f6e838d7bbb0aec85/docs/acceptance/r2-06/release-verification.json)确认 Deploy 在 `09:44:21 UTC` 完成，未跳过发布。

[24 项交付核对](r2-06/delivery.json)全部通过：[运行/源码](https://github.com/LinsRock/unspun/blob/eb5b19f749c8316174e9cc5f6e838d7bbb0aec85/docs/acceptance/r2-06/postdeploy-runtime.json)、[schema](https://github.com/LinsRock/unspun/blob/eb5b19f749c8316174e9cc5f6e838d7bbb0aec85/docs/acceptance/r2-06/postdeploy-schema.json)及[服务审计](https://github.com/LinsRock/unspun/blob/eb5b19f749c8316174e9cc5f6e838d7bbb0aec85/docs/acceptance/r2-06/postdeploy-audit.json)确认生产 `000019`、七张话题/新链表均为 0；API/受控 worker 同一固定 `78061d7…` 镜像，89 个源码/四份配置匹配，web 复用原固定镜像。legacy 所有状态 0、受控 worker 1，唯一发布端口仍为 `127.0.0.1:8080`。

[生产新链](https://github.com/LinsRock/unspun/blob/eb5b19f749c8316174e9cc5f6e838d7bbb0aec85/docs/acceptance/r2-06/postdeploy-member-chain.json)开关 false、runtime 无新 handler、新任务与调用均为空；三个新阶段未分配，原政策行和上限未改变。没有生产话题回填、自动新增任务或新阶段付费。[前](https://github.com/LinsRock/unspun/blob/eb5b19f749c8316174e9cc5f6e838d7bbb0aec85/docs/acceptance/r2-06/predeploy-reading.json)/[后](https://github.com/LinsRock/unspun/blob/eb5b19f749c8316174e9cc5f6e838d7bbb0aec85/docs/acceptance/r2-06/postdeploy-reading.json)各 113 个合格详情的集合/正文散列、推荐/最新前两页及停源 404 一致；读取没有排任务。[生产账务](https://github.com/LinsRock/unspun/blob/eb5b19f749c8316174e9cc5f6e838d7bbb0aec85/docs/acceptance/r2-06/postdeploy-production.json)已知费用差额 0；[原评测](r2-06/postdeploy-evaluation.json)七笔未知、完整 $0.484867 预留、已知费用/政策/carry 保持，本批新付费 0。

[旧资源/身份/反馈](https://github.com/LinsRock/unspun/blob/eb5b19f749c8316174e9cc5f6e838d7bbb0aec85/docs/acceptance/r2-06/postdeploy-retained.json)、[旧业务/积压](https://github.com/LinsRock/unspun/blob/eb5b19f749c8316174e9cc5f6e838d7bbb0aec85/docs/acceptance/r2-06/postdeploy-protected-production.json)保持。[原观察环境](https://github.com/LinsRock/unspun/blob/eb5b19f749c8316174e9cc5f6e838d7bbb0aec85/docs/acceptance/r2-06/postdeploy-observation.json)确认 3 个 R2-04 容器 ID、镜像、状态、启动时间、重启数与挂载未改，此前 127 份原件散列保留，本次截面仍为 127 份；后续轮次由原观察进程继续追加；本批不签核观察或启源。所有隔离库/备份/镜像及 worktree 保留。部署后证据由纯文档 PR 补录，其提交不等同新的运行发布。

下一批尚缺：固定真实材料及留出上的模型判断/审核评测，分别报告误合并和漏归并/覆盖（包括同主体不同事件、转载、独立观点、部分重叠、长背景、多话题及未知时间）；可审计的后台补成员/依据、纠错和费用/任务下钻；刷新原账本/提供方后审查真实费用与总额内分配，再经明确配置 PR 有限启用及自然运行/恢复验收。R2-06 整体保持未完成，生产继续关闭。
