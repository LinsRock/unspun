# CL-04A · 旧批处理入口核对与独立死代码清理

本批按 [D-048](../decisions.md#d-048--2026-10-28--cl-04a-只提前清理独立死代码) 提前处理独立死代码，**不代表完整 CL-04 验收**；完整清单仍待 R2-11。基线为最新 `origin/main` **`92f5018766b68b6633f4ec41a58399b43d1efd8b`**，独立 worktree `~/.config/superpowers/worktrees/unspun/cl-04a-dead-code`，独立 venv。日报生成与历史快照职责仍归 CL-06。

## 删除前依赖核对与处置

静态检查覆盖全部 Git 跟踪文件、Python 导入与函数调用、显式 runtime handler 注册、`__main__`/argparse/打包入口、Compose/部署/CI、当前评测、CL-00/01 恢复说明，以及 R2-11 三个保留缓存和 CL-05 恢复缓存的脚本/登记。未发现符号动态查找或外部命令注册；此结论限于仓库与已登记的本机资源，不虚构最后使用时间。未运行旧批处理来核查存活性。

| 已核对对象 | 当前入边和实际处置 |
| --- | --- |
| `cluster.cluster_pending` | 仅一项专属批处理测试；无运行/CLI/评测/恢复调用，已删除包装、`CLUSTER_BATCH_LIMIT`、专属 `is_legacy` / `session_scope` / `get_logger` / `get_scoring_params` / `ready_condition` 导入和 logger；删除 `test_clustering_does_not_assign_r1_even_when_legacy_ready` |
| `score.score_pending` | 无调用；删除包装 |
| `score.refresh_pending_public_impact` | 仅上一包装及一项 mock 测试调用；已删除批量扫描，与上一包装共有的 `select` / `text` / `selectinload` / `session_scope` / `get_logger` / `get_scoring_params` / `load_sources` 导入和 logger；提供方失败后恢复的历史断言保留在共享单事件函数测试中 |
| `summarize.embed_pending` | 无调用或专属测试；删除包装、`EMBED_BATCH_SIZE`、`batched` 及仅供该包装的 `refresh_centroid` 导入 |
| `summarize.summarize_pending`、`viewpoints.viewpoints_pending` | 仍承载历史费用保留、预算停止/恢复、重复输入复用及有界失败尝试复现；本批保留源码与相关测试，不因旧 worker 退役直接判死 |

恢复使用上述固定基线的完整 checkout/worktree；不要把旧包装重新接回当前 worker 或在现有业务库运行。历史评测按各自冻结 revision 复现，不修改输入/哈希以适配本批。

实际删除 **4 个函数、2 个常量、2 个 logger 及专属导入**，三个源码文件合计减少 **157 行**（8 行新增、165 行移出，包括失效的自动批处理说明）。没有整文件/整模块删除。只删除上述 1 项专属测试；`test_pending_impact_retry_recovers_without_importance_call` 改名为 `test_impact_retry_recovers_without_importance_call`，保留真实异常模拟、冷却后恢复、不重复请求和原评分/时间不变断言，改走 `refresh_event_public_impact`。

## 保留的实际依赖

- `score.pending_score_conditions`、摘要/embedding 积压谓词：`api/report.py`、`api/admin/runs.py` 和历史查询继续使用。
- `score_event`、`refresh_event_public_impact`、摘要/embedding 单对象函数及观点函数：显式 `repair_grounding`、当前质量评测或历史失败/资格回归继续使用；不整模块删除。
- `assign_article`、`refresh_centroid`：历史聚类、R1 拒绝进入旧处理链的隔离回归保留；共享函数及断言不随包装一起删除。
- `embed_batch_limit`、`score_batch_limit`：现有配置模型、后台配置响应和页面仍引用，保持 API 契约及历史解释能力；本批不把展示字段当作执行注册。
- `digest.py`、日报 API、历史快照、页面、模型/预算/来源/部署配置、迁移和业务数据均不改。完整 CL-04 的排序/偏好/页面精简及历史生产复验仍待后续，日报归 CL-06。

## 验证与交付

新库 `unspun_cl04a_20261028_144138` 迁移至 `000021`，仅使用合成夹具和 mock；无真实 key，并用本机 pytest 拦截器拒绝外部 socket 和全部六个旧批处理入口。普通日志/拦截器/资源登记仅留 `~/.cache/unspun/cl-04a-dead-code-20261028/`，不作为新生产入口。新库、worktree/venv 和登记保留供审查；未写既有库或清理既有资源。

为遵守本批禁止执行旧批处理的要求，**13 项必要历史复现案例保留原断言**，仅增加 `legacy_batch` 标记；pytest 默认排除该标记，现有 CI 使用同一默认。它们覆盖摘要失败后费用提交、预算停止/草稿恢复、重复输入复用、观点失败尝试上限和轮转。显式历史重放留到对应授权批次，当前回归不借此触发旧包装。当前受控 worker 的任务、预算/未知预留、资格、修复与历史查询测试仍默认执行。

测试总收集数从 **1,369 → 1,368（净减 1）**；按本批禁跑范围，基线为 1,354 项可执行、15 项保留但排除，终版为 **1,355 项可执行、13 项历史排除**（单事件恢复测试重新纳入）。基线初次运行 1 项因本批回环 URL 覆盖与冻结 provider URL 校验不符而失败；恢复预期 URL 后定向通过，外网拦截保持，没有修改业务代码或证据迁就测试。

终版后端完整受控回归 **1,355 项通过、13 项历史排除、0 失败/跳过**，覆盖 worker 队列/租约/恢复、历史事件/日报/后台查询、公开资格、预算/未知预留/费用、修复、共享评分和受影响调用方。三个修改模块 **18 个保留函数 AST 完全不变**；固定 **40 例排序通过**（ready/pass 均 true，issues 0）；Ruff/格式/Pyright、前端 **142 项**及 lint/typecheck/build/PWA 离线检查、CI 路由 **11 项**通过。本批 `pyproject.toml` 的测试配置变化依既有规则联动 Web 回归，不修改页面。CI 选择 server/web 与 server 镜像发布，Web 镜像复用，未选择原型或部署脚本回归。

审查覆盖本批差异及调用方、动态注册/运维/恢复引用、旧包装禁跑和历史测试保留边界；未发现未解决问题。76 个本地文档链接及差异格式通过；冻结评测、config、API/core、schema、页面和部署文件与基线逐文件一致。R2-11 三个缓存及 R2-04 保留 worktree 的 **635 份文件**哈希保持（其中 R2-04 工作区 `docs/` **464 份**）；旧原件登记、任务板结论和完整 CL-04 四项验收清单不改。

[PR #146](https://github.com/LinsRock/unspun/pull/146) 的最终 head `47eb646` 在[必需 CI 第 2 次尝试](https://github.com/LinsRock/unspun/actions/runs/40673168603/attempts/2)全部实际通过后，于 **2026-10-28 10:43:35 UTC** 合并为 **`23d654d1229aa4d059eb796cd3f46daa04b4dea7`**。首轮 Web 在未改动的 `CostsPage.test.tsx` 触及默认 5 秒超时，141 项通过、1 项超时；保留[首次失败](https://github.com/LinsRock/unspun/actions/runs/40673168603/attempts/1)，同一 head 按失败作业重跑后 Web/汇总通过，没有改页面、断言或超时门槛。后端 CI 同样为 1,355 通过、13 项排除，固定 40 例通过。

[主干 CI/自动发布](https://github.com/LinsRock/unspun/actions/runs/40674388149)全部成功，server/web/required-checks、镜像构建及 `Deploy` 均实际执行通过。主干后端同为 **1,355 通过、13 排除**，40 例排序通过；没有因耗时较长重跑或提前部署。

**2026-10-28 10:56 UTC** 只读核对：API 和受控 worker 的实际 server 镜像及 `APP_VERSION` 均为 **`23d654d1229aa4d059eb796cd3f46daa04b4dea7`**；Web 复用固定 **`4042f20ddae82b9282e8c3b57c5c99bbcb430125`** 镜像。API 的 mixed/发现首页仍为 true，成员处理/合成/话题发布/话题偏好仍为 false；worker 的 R1 开关为 true、所有 R2 开关为 false。核对仅读取版本/设置，没有 mixed HTTP、观察脚本、手动部署或额外生产数据探针。部署后再次核验上述 635 份文件哈希一致。

R2-11 保持 **8/12 暂缓**，不追加 mixed 观察、不修改接续资源；新增模型付费、提供方查询、生产数据清理和 R3 均 **0**，不宣称原 R1 自然活动全窗口零费用。本次后续文档提交不改变上述实际运行版本。
