# CL-04 首批 · 依赖梳理与兼容精简

本批由用户于 2026-10-30 授权提前开展静态核查及等价精简，基线为 `origin/main` **`45615d40af164a09b261885bd3309db119877ac2`**。完整退役仍依赖 R2-11；**8/12 暂缓、不补记验收通过**。CL-04A 的四个包装保持删除，CL-04B 的镜像边界保持，不重复实施。依据见 [D-031](../decisions.md#d-031--2026-10-19--分阶段安排旧链路文档及无用过时数据清理)、[D-048](../decisions.md#d-048--2026-10-28--cl-04a-只提前清理独立死代码)、[D-049](../decisions.md#d-049--2026-10-29--cl-04b-仅收敛生产镜像内容)及[清理任务板](../tasks/cleanup.md)。

实施顺序：先核对注册/调用/恢复及隔离基线；将旧积压的只读查询集中到共享模块、合并重复计数并保留导入兼容；比较 SQL/API/函数契约，再做完整回归、审查和 PR/CI。没有页面修改，不触发 D-012 的新体验验收；自动化前端检查不冒充用户体验。

## 逐符号处置

以下结论限于 Git 跟踪源码、显式运行注册、CLI/部署/CI、现用评测及已登记的恢复资源。静态无匹配只作为线索，不证明没有仓库外使用者；未执行旧批处理或提供方调用来判定存活性。

### 本批可合并与移除的重复实现

| 对象 | 入边、处置与兼容 |
| --- | --- |
| `summarize.pending_summary_conditions` | `pending_summary_ids`、`summarize_pending`、报告/后台积压读取；原实现迁到 `core.legacy_backlog`，旧路径保留同一函数的显式重导出。保留 input hash、阅读版本、审核/语言原因、失败上限及 legacy owner 条件 |
| `summarize.abandoned_summary_conditions` | 报告放弃清单、后台分页、R1 隔离回归；同上迁移，失败上限边界和原 `pending_summary_conditions()[0]` 保持 |
| `summarize.pending_embedding_conditions` | 报告、后台及 R1 排除回归；同上迁移，ready/embedding 空值/legacy 三条件保持 |
| `summarize.summary_ordering` | `pending_summary_ids` 与后台积压分页；同上迁移，原始发布时间降序/未知末位、review-limited 优先、ID 降序保持 |
| `score.pending_score_conditions` | 报告、后台、R1 混合所有权排除回归；同上迁移，评分失效与 `legacy_event_condition` 保持，旧路径仍可导入 |
| `report.daily_report` 与 `admin.runs.get_backlog` 内四类重复计数 | 合并到 `legacy_backlog.backlog_counts`；仍执行四条原计数查询，返回相同整数/零值。报告继续映射 `abandoned_summaries` 为原字段 `abandoned_total`，后台字段及分页不变。只移除重复计数正文、旧定义位置和失效导入 |
| `PipelineParams` 注释、`server/tests/README.md` | 纠正“旧批次上限驱动当前 worker”的过时说明，并将默认收集数量更新到最新主干；参数/默认值/校验、测试正文和 marker 不变 |

没有另行证明可删除的整模块或业务入口。函数移动不计作功能退役，五个旧符号仍可导入。两个 API 不再为积压读取直接加载 `pipeline.summarize` / `pipeline.score`；日报、修复和评测的必要依赖不裁剪。

实际源码差异：`admin/runs.py` 减少 20 行、`report.py` 减少 16 行、`score.py` 减少 8 行、`summarize.py` 减少 36 行，新共享模块 80 行，`params.py` 仅等行注释修改；**源码净行数变化 0**。收益是两份计数实现收敛为一份、五个查询的依赖归属明确，API 不再加载两个旧生成模块；没有宣称删掉五项功能、释放磁盘或测得性能提升。

### 必须保留的运行、历史及恢复依赖

| 精确对象 | 实际入边 / 保留原因 / 后续归属 |
| --- | --- |
| `api.events.list_events`、`event_out`、`EventOut`、`viewpoint_out`；`core.feed_query.feed_page`、`decode_cursor`、`publisher_aliases`、`window_start` | `app.include_router(events_router)` → `/api/events`；`web/api.ts.fetchEvents`、`FeedPage` 和日报快照序列化仍调用。保留旧排序/筛选/游标、原始时间、媒体组和历史来源名称回退。行为退役待 R2-11 后重新验收 |
| `api.events.get_db` | 事件、日报、报告、内容/话题/读者及多项后台依赖的同一 REPEATABLE READ / READ ONLY 会话；测试也以同一函数对象覆盖依赖。不是仅属旧页面的包装，本批保留 |
| `api.feed_preferences.Preferences`、`PreferencesInput`、`preferences`、`get_preferences`、`put_preferences` | `/api/feed-preferences` 与旧 `FeedPage` 持久化排序/时间范围；CAS 冲突及现有默认值必须保留。不能与新版 ReaderState/TopicPreference 合并身份或版本 |
| `api.feed_preferences.get_write_db`、`Db`、`require_write`；`admin.auth.require_admin_identity`、`admin.expenses.same_origin` | 新旧读者反馈、偏好和导读请求共享写事务、身份与同源校验；保留 401/403/409、撤销和幂等语义 |
| `App` 的 `/` 旧查询参数分支、`/events`、`/history`、`/digest`、`/report`；`FeedPage`、`DigestPage`、`ReportPanel` | 旧链接仍能打开；发现首页/混合开关关闭及 capabilities 失败仍有原回退。`/reading/:id`、`/topics/:id` 与后台详情继续独立。本批 Web 文件无修改；减少入口或展示须另过 R2-11 与 D-012 |
| `cluster.assign_article`、`refresh_centroid` | 无受控 worker handler，仍有 `test_summarize_cluster` 的旧聚类/归一化和 `test_content_foundation` 的 R1 拒入回归；不是仅凭无生产调度就可删。保留历史重现；后续须确定冻结复现承载方式 |
| `score.objective_score`、`importance_user_prompt`、`score_event`、`refresh_event_public_impact`、`_clamp_band` | `repair_grounding.repair_event` 显式修复、`test_score` 的失败冷却后恢复与不重复调用、`test_content_foundation` 的所有权隔离。保留评分、原始时间与影响证据，不恢复已删批处理 |
| `summarize.summarize_article`、`embed_articles` | `repair_grounding` CLI；`evaluation.run_quality`、`evaluation.content_quality` 仍比较旧摘要/质量行为，另有摘要 grounding/费用测试。保留真实费用和失败重现入口，本批只 mock |
| `summarize.pending_summary_ids`、`record_summary_failure`、`hydrate_legacy_publications`、`summarize_pending` | 历史优先级、已验证旧标题补读、重复输入复用、预算暂停/恢复和失败费用提交的 mock 回归；不注册到受控 worker。完整退役不能删除这组尚无替代的证据 |
| `viewpoints.input_fingerprint`、`is_eligible`、`prompt_articles`、`viewpoint_evidence_sources`、`viewpoint_user_prompt`、`parse_viewpoints_payload`、`refresh_event_viewpoint`、`candidate_viewpoint_ids`、`viewpoints_pending` | 显式修复及质量评测调用单事件函数；历史 mock 继续核对资格、失败尝试上限/轮转、费用与恢复。私有解析/存储辅助随调用保留，不因模块名“旧”删除 |
| `repair_grounding.UsageCommittingClient`、`copy_article`、`repair_event`、`main` | `python -m unspun.pipeline.repair_grounding` 为显式运维/修复入口，含 usage 独立提交、锁定和合格结果原子替换；本批不执行修复，不移除必要恢复能力 |
| `admin.runs.list_runs/get_run/get_backlog`、`admin.content.list_articles/read_article/list_events/read_event`、`report.daily_report` | 后台和兼容 `/report` 继续读取历史 PipelineRun、Article、Event、LlmUsage/FetchLog；历史未知运行状态不补成成功，费用分母和缺失字段保持 |
| `admin.content._safe_viewpoint` 与 `api.events.viewpoint_out` | 有意不合并：前者保留原 payload 的可诊断字段并检查严格整数/去重，后者 Pydantic 校验失败返回无观点并带日志，公开页另有中文限制。统一实现会改变损坏历史记录的容错 |
| `core.reading.current_reading`、`ready_condition`、`input_hash_expression`、`event_reading`、`refresh_event_text`、`hydrate_legacy_reading`、`chinese_text`；`core.grounding` 证据函数 | 新旧阅读、内容处理、资格、摘要/观点和评测共享；原文/阅读版本变化失效，不将未审核材料当历史可读。`core.public_impact.assess_impact/impact_fingerprint/unknown_impact` 仍由单事件修复使用 |
| `core.content.is_legacy/require_legacy/legacy_event_condition/fingerprint` | 所有权隔离、规范身份、派生指纹、任务与费用去重共同依赖，不能随旧聚类删除 |
| `core.reader.snapshot/mutate/feedback_target/feedback_group/effective_feedback`、`reader_targets.change_topic_preference`；`content_publication.current_versions/qualified_item/qualified_items` | 新版独立内容/话题/混合流、反馈撤销、别名与历史详情准入仍调用。保留身份 CAS、用户版本、幂等请求和来源/材料/派生失效，历史详情继续不受列表候选上限裁剪 |
| `r1_runtime.build_runtime/main`、`r1_worker.process_one/WorkerPool`、`DiscoveryHandler`、`MaterialHandler`、`ContentHandler`、关闭的 `MemberHandler/SynthesisHandler` | 显式 `(queue, kind)` 注册只含 discover/fetch_material/process_card/process_guide 及受开关控制的话题任务；没有旧摘要/聚类/评分/日报 handler。受控 R1 继续保持，新链开关和 allocation 不动 |
| `core.tasks.enqueue/claim/reap_expired/complete/fail/schedule_sources`；`discovery_quotas.select_materials/select_processing/record_processing` | 任务去重、租约/晚到 CAS、恢复、配额收据与分母是现用路径；终态/旧任务不能因清理丢失。模块与表均保留 |
| `core.billing.DatabaseJournal.reserve/identify/finish/unknown/reconcile`、`initialize_budget/budget_status`；`core.llm.LlmClient`、`review_budget.require_grounding_budget` | 受控处理、修复、评测和账务 CLI 共享。未知预留不得释放或补零；不改模型、总额、阶段分配、paid-stop 或失败记录，本批不查询提供方 |
| `ScoringParams` / `PipelineParams` 的 `embed_batch_limit/score_batch_limit/summary_batch_limit/max_summary_failures`、`offcircle_ratio`、旧模型环境变量；`scoring.yml/media_groups.yml` | 前两项仍由后台配置 DTO/页面暴露；其他项分别参与保留包装、修复/评测、必填配置兼容或冻结解释。配置展示不等于运行注册；没有移除值、来源 ID 或环境变量 |
| `evaluation.feed_ranking.rank_events/window_start` 与 `core.feed_query` | 固定 40 例的离线参考与 PostgreSQL 实现互相校验，类型/边界参数也不同；不为减少重复而将评测变成自证。`run_feed_ranking` CLI、旧质量 CLI、preview seed 均保留；历史按登记 revision 复现 |

### CL-06 日报依赖及恢复

`api.digest.latest_digest/historical_digest/digest_response` → `pipeline.digest.DigestPayload` → `api.events.EventOut` 保持；已存日报的 payload、日期选择与 PWA/IndexedDB 离线历史仍可读。`digest.due_report_date/select_digest_events/generate_digest/digest_pending` 及 `DigestParams` 的时区/时刻/top_n、`Settings.digest_model` 保留，mock 仍验证按日期幂等、失败保留 usage 和旧快照。没有当前 worker 调度不代表本批获准退役；生成与重复展示归 **CL-06，等待 R3 新精选/首页及持续使用验收**，不能跟随 CL-04 提前删除。

恢复采用本批基线完整独立 checkout，或经 PR 回退本批的源码变更；无迁移、无数据修改，不需要重抓/重生成。部署继续使用已退役 legacy 服务后的 Compose/`deploy.sh`，固定镜像回退也只能运行受控消费者。历史评测按原记录的完整 revision 和原件恢复，不把老 worker 的 Compose 拉回主干。

R2-11 三个缓存目录中的观察/rollback/restore、R2-04 v1/v2 工作区及当前原件仅检查依赖/字节，不执行接续脚本。保留路径及恢复入口分别见 [R2-11 交接](r2-11-reading-enablement-2026-10-26.md)、[R2-04 交接](r2-04-source-increments-2026-10-20.md)和[本机回收登记](cl-local-lab-reclamation-2026-10-30.md)。不依赖已回收的 CL-01/04A/B 实验容器或卷。

## 验证与资源

独立 worktree：`~/.config/superpowers/worktrees/unspun/cl-04-compat-20261030`；独立 `server/.venv` 指向本工作区。本批资源归属和普通日志仅存 `~/.cache/unspun/cl-04-compat-20261030/registration.json` 及同目录，不提交整套日志、快照或 JUnit。

按 [测试说明](../../server/tests/README.md)新建 `unspun-cl04-compat-20261030-db`、`unspun_test`、专属 `*-data` 卷和 `*-internal` 网络，无发布端口。测试容器只共享这个新库的网络空间、源码只读挂载；真实 key 为空，原 mock 客户端保持。迁移到 `000021` 后先验证空库/空 key、唯一 internal 网络和原生 IPv4/IPv6 外连失败，再执行 13 项及默认完整回归。

测试数量：CL-04B 的 1,368 到本次基线 **1,383**，差额全部来自已合并的 [PR #153](https://github.com/LinsRock/unspun/pull/153) `test_public_sources.py`：`test_paper_qualified_and_unsupported_labels_are_not_people` 4 项、`test_paper_source_and_design_boundaries_stop_editor_role_propagation` 2 项、`test_paper_explicit_outlet_credit_keeps_personal_author_unknown` 6 项、`test_paper_reprint_keeps_people_separate_from_credited_outlet` 1 项、`test_paper_outlet_after_source_boundary_preserves_preceding_person` 2 项。本批测试增删 **0**，13 项 `legacy_batch` 默认覆盖、全部断言与 marker 保持。

首轮未改源码的隔离基线：13 项先通过，完整回归 **1,382 通过 / 1 失败**；失败为 `test_reviewed_chain_and_atomic_idempotent_successors[explanation-explanation]` 的 `topic_review` 领取返回空。原样复跑成员处理模块 **43 项通过**；保留首轮记录，不将原因推定成已证实的环境问题，不改业务代码/断言/超时来消除失败。

随后完整未改源码基线 **1,383 项全部通过**，再实施本批源码修改。五个迁移函数及其余保留函数共 **16 个函数 AST 完全一致**，配置模型 AST 也一致；完整 OpenAPI、四类计数谓词 SQL 和排序 SQL 与基线逐字节一致。直接比较基线/当前报告及后台函数：空库和非对称合成夹具、四个 stage 的两页均相同，夹具覆盖 R1 排除、材料与阅读版本失效（计数为待摘要 9、待 embedding 3、待评分 2、放弃 2）；比较事务已回滚，五个旧导入与共享函数对象一致。定向 **57 项通过**。

Ruff/224 文件格式/Pyright 通过；前端 **142 项**、lint/typecheck/build/PWA 离线检查通过。PWA 临时预览单独登记端口/PID并关闭代理，验证后停止；没有访问既有 API/预览服务或修改页面。CI 路由 **11 项**、部署安全 **19 项**及 Bash 语法通过；分类器选后端/Web 检查和 server 发布，Web 镜像复用，不更改 CI 范围规则。构建最终运行镜像后在 `--network none` 下确认新增共享模块随原 CL-04B 白名单进入镜像，API 导入不加载旧摘要/评分模块，受控 worker/修复模块可导入、修复 CLI `--help` 与兼容别名可用；未启动 worker 或修复任务。

固定 **40 例排序通过**（ready/pass true、issues 0）。本机终版先通过 13 项，完整回归 **1,382 通过 / 1 失败**；`test_receipt_substitution_cannot_authorize_cas[response_fingerprint]` 在 `topic_recall` 领取时返回空。追加三轮成员处理/凭证诊断为 **182 通过 / 1 失败**，一次模块复核为 **60 通过 / 1 失败**，均为原 `explanation` 案例的账务时间排序断言，未修改测试。本机合成队列 2,000 次领取未复现；独立 55 秒原生时钟记录捕获五次墙钟倒退 **106–128 ms**，单调时钟仍前进约 1–2 ms，且与凭证顺序异常时刻吻合。这与刚入队任务暂时未到期及先后请求按墙钟排序异常一致，不能将这些失败抹去或宣称所有本机终版回归已通过。

为保护现有 R2-04/11 及其他服务，不调整共享 Colima 的时钟/同步服务、不改测试时钟/重试/断言、不排除用例。最终完整回归在既有 CI 的新 Linux runner、新 Postgres 服务和 internal 网络完成；本机失败日志/只读诊断留本批缓存，CI 结果与收尾完成后补录。

差异及受影响调用方审查覆盖 SQL/零值/分页、导入兼容、配置默认值、API 身份/事务、运行注册、修复/历史读取、任务/配额/账务和镜像打包；应用变更未发现未解决问题。本批源码以外的 config YAML、迁移、Web、测试正文/marker、依赖声明/lock、部署/CI、R2 任务板均与基线一致。**442 份原验收/评测文件及 1,174 份登记的本机保护文件**字节保持；99 个本地文档链接与 `git diff --check` 通过。本批不把工程通过计入 R2-11、真实语义或用户体验验收。
