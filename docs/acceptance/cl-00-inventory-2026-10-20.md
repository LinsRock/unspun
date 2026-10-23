# CL-00 只读盘点与处置清单 · 2026-10-20

**CL-00 已完成盘点；CL-01–06 未实施。** 下一维护批次可按下表退役旧 worker，不需要先删除业务数据或共享模块。没有删除、移动或归档原件，没有启动处理、初始化账务、付费、迁移或发布运行时。

基线为最新 `origin/main` **dc7c173**，独立分支 `docs/cl-00-inventory`，worktree `~/.config/superpowers/worktrees/unspun/cl-00-inventory`。先读 CLAUDE、D-031/032、清理/R2 任务板及 R2-03 验收。观测主要在 **05:13–05:20 UTC**；生产仍为 R2-03 `6f4fe4f`，schema `000017`，web `8dd144b`。原评测库位于本机 Postgres，schema `000015`。

[处置登记](https://github.com/LinsRock/unspun/blob/eb5b19f749c8316174e9cc5f6e838d7bbb0aec85/docs/acceptance/cl-00/disposition-register.json)的 **1,095 条记录**逐项含对象/谓词、环境/归属、实测数量/字节、引用/活跃状态、建议、理由、恢复入口和 CL 任务。记录有交叉视角，不能相加当成独立对象数或可释放空间。`delete` 仅指未来 CL-01 的 8 项动作；`archive` 是 CL-02 历史索引建议，冻结原件保持路径与字节；未知均为 `pending`。本轮实际删除/归档量均为 **0**。

## CL-01 的完整边界与精确动作

[32 个第一方传递依赖](https://github.com/LinsRock/unspun/blob/eb5b19f749c8316174e9cc5f6e838d7bbb0aec85/docs/acceptance/cl-00/legacy-dependency-closure.json)中，只有 `main.py`、`fetcher.py` 不被当前 API/R1 或保留评测入口触达；全仓 Python AST、命令字符串和调用方复核见[引用清单](https://github.com/LinsRock/unspun/blob/eb5b19f749c8316174e9cc5f6e838d7bbb0aec85/docs/acceptance/cl-00/code-references.json)。包无额外 console entry；共享 server 镜像默认 CMD 是 API。

| 精确对象 | 实测范围 | CL-01 建议及恢复入口 |
| --- | --- | --- |
| `server/src/unspun/pipeline/main.py` | 2,447 B；只被 Compose 和专属测试启动/导入 | delete：旧轮询、AI 编排及 `PipelineRun` 写入入口；恢复用基线 Git blob，不能恢复付费循环运行 |
| `server/src/unspun/pipeline/fetcher.py` | 5,370 B；仅 main 和 `test_fetcher.py` 调用 | delete：旧串行抓取器；其 feeds/extract/publication 工具保留 |
| `server/tests/test_pipeline_main.py`、`test_fetcher.py` | 931 / 3,913 B；2 / 4 项测试 | delete：随专属实现移除；不删除共享 feeds、材料、隔离归属或发布回归 |
| `deploy/compose.yml :: services.worker` | 一个服务块；字节数见登记 | delete：包括旧命令及专属环境/依赖；整个 Compose 文件保留 |
| `deploy/compose.prod.yml :: services.worker` | 一个零副本/无重启块 | delete：与基础服务及脚本参数同批移除，保留 `r1-worker` 的 1 副本/重启/资源限制 |
| `deploy/deploy.sh :: --scale worker=0` | 一处参数 | delete 参数并改相邻旧注释；保留 `--remove-orphans`、固定镜像、DB→迁移→预算/预检→启动→目标 health 顺序及中断保护 |
| `deploy/compose.local.yml` 的 `# worker reuses ...` 注释 | 一处注释 | delete：只移除过时说明，本地其他服务/端口不变 |
| `deploy/tests/test_deploy.py:110,127` | 两处 `worker=0` 断言，文件仍有其他部署用例 | keep 并改断言为不定义/不启动 legacy；保留付费围栏、失败关闭、镜像复用、迁移与中断测试 |
| `deploy/tests/verify_startup.py`、`test_verifier_process.py`、`server.Dockerfile`、`.github/workflows/ci.yml`、`.github/scripts/ci_scope.py` | API-only 启动验证、共享镜像及按路径选择的 backend/deploy 检查 | keep；没有独立 legacy CI job 可删，CL-01 应按原分类器执行受影响回归 |
| CLAUDE、清理板、`docs/tasks/r1.md` 中旧源码链接及启动说明 | 引用逐项保存在清单 | 更新当前入口；历史正文保留，删除源码导致的历史链接改为基线固定 blob 链接，不改冻结结果 |

源码/专属测试共 **4 文件、12,661 B**；其他动作是局部编辑，不能把其所在共享文件删除。恢复基线为 `git show dc7c173:<path>`，运行回退必须沿用退役后的部署文件及受控消费者。

**运行与回退边界：** [Compose 渲染](https://github.com/LinsRock/unspun/blob/eb5b19f749c8316174e9cc5f6e838d7bbb0aec85/docs/acceptance/cl-00/compose.json)核对基础、本地、生产三种组合；当前基础/本地仍默认包含可启动的旧 worker，生产才是 scale 0/restart no，故不能只删生产零副本声明。生产四份部署文件哈希与基线一致；[实际资源](https://github.com/LinsRock/unspun/blob/eb5b19f749c8316174e9cc5f6e838d7bbb0aec85/docs/acceptance/cl-00/production-resources.json)确认旧 worker 容器 **0**、`r1-worker` **1**，唯一发布端口 `127.0.0.1:8080`。本轮未运行 compose up/run、deploy.sh 或任何 worker 命令。

保留当前 server **6f4fe4ff38c0b109f5d4648cddda0d4ae476fb93**、上一已发布 server **43150075d33e17298a21bfa909fac578f5d511d9**、web **8dd144bc6cf5775e5dfe881cbdc50472bedb6486** 的固定镜像/digest。CL-01 需在隔离环境验证三种 Compose 均无 legacy 服务、正常部署/停止/重启、上述旧固定镜像回退及失败路径；回退使用退役后的脚本/Compose，不能整体恢复旧配置。CL-00 的 config/只读探针不冒充这些运行验收。

[旧积压只读查询](https://github.com/LinsRock/unspun/blob/eb5b19f749c8316174e9cc5f6e838d7bbb0aec85/docs/acceptance/cl-00/legacy-backlog.json)仍报告 **8,825** 个摘要待处理、**18** 个摘要失败上限对象，embedding/score 待处理均 0；配置还有 **58** 个 legacy-enabled 条目。它们是旧字段/配置语义，不能记为“没有剩余业务”或补造完成。截面未见 legacy owner 的调度状态；实际 `source_states` 为 R1 的 8 启用/6 关闭。旧循环没有持久任务领取机制，旧字段积压也未获恢复处理授权。退役执行器不处理或删除旧积压，不移除历史来源名称，不恢复旧抓取/付费。

**CL-01 必须保留并转交：** `summarize.py`、`score.py` 仍供 report/admin backlog 及冻结评测使用；`cluster.py` 被摘要/修复/旧回归使用；`viewpoints.py`、`repair_grounding.py` 仍有历史质量/复现用途，交 **CL-04**。`digest.py` 的 payload 契约仍被 `/api/digest` 导入，生成/历史快照及前端日报、离线读取交 **CL-06**。其余传递依赖的精确路径、体积和入边见登记：保留 core 的配置、模型、DB、LLM、审核/账务及全部身份/材料/任务语义，保留 `r1_worker.py`、`r1_runtime.py`、discovery/quotas、材料、生成、公共源及 feeds/extract/editions；CL-01 不在共享文件内做符号级清理。

## 文档、原型与有效历史待办

[基线逐文件清单](https://github.com/LinsRock/unspun/blob/eb5b19f749c8316174e9cc5f6e838d7bbb0aec85/docs/acceptance/cl-00/documents.json)：**342 文件、13,070,957 B**，记录 SHA-256 和字面 Markdown 入链；无入链不作为可删依据。唯一字节相同组是 M3-B `frozen-ranking-report.json` / R1 `legacy-regression-v1.json`，两条历史/冻结入口都保留。[冻结核验](https://github.com/LinsRock/unspun/blob/eb5b19f749c8316174e9cc5f6e838d7bbb0aec85/docs/acceptance/cl-00/frozen-check.json) **27/27** 相符，sources 使用冻结 revision；v1、scan v2、candidate v3、原 43 条及新增用户空评分不改写。

| 精确范围（逐文件路径见登记） | 数量 / 逻辑字节 | 建议、独有信息及承接 |
| --- | --- | --- |
| `requirement-legacy-2026-10-15.md`、`roadmaps-legacy-2026-10-15.md` | 2 / 60,008 B | archive，保留旧需求、结案与未齐证据；当前入口转新版，CL-02 不复制全文 |
| `docs/superpowers/` | 25 / 152,888 B | 当前 R2 spec keep；旧计划/spec archive 索引，包含执行契约与决策原因，不能目录批删 |
| `docs/acceptance/r1-session-handoff-2026-10-17.md`、`...18.md` | 2 / 22,991 B | archive；有原费用/预留、失效端口、保留库与导入依赖，当前值以本报告替代，原件仍可追溯 |
| `docs/design/m3a-admin/`、`m3a-admin-react/` | 11 / 142,643 B；14 / 153,580 B | archive；各有交互/组件选型、用户验收与 vendor 许可，React 原型还受 CI 路径检查，未证明可直接删除 |
| `docs/design/admin-operations/` | 8 / 1,084,632 B（含 7 PNG） | archive；真实验收截图与唯一第二轮反馈依据，不能只按“旧截图”删除 |
| `docs/design/r0-reading/` | 11 / 131,331 B（Git 内） | keep；原型验收、43 候选、材料指纹及尚空的反馈入口仍有效；本地正文缓存另保留 |

历史未结事项接回当前入口，**不把映射视作新功能交付**：M1 A5/旧 M3 人工排序与值得读反馈 → **R2-11/R3**；R0 来源连续性、社区/视频实际材料与受限源缺口、NHK/旧 63 源稳定性 → **source-plan / R2-04**。旧 M3 E → **R2-05–07**；旧 F/精选密度更新参数、七天新运行和生产手机离线证据 → **R3**。M2 七天旧日报、#43 涉及事件 1368/117、文章 2035 的历史生产复验仍未证实，分别交 **CL-06、CL-04** 保留/核查，不能靠重启旧循环补证。旧 C1 的已交付部分以 R1-03/04 为准；C2 手动纠错、C3 配置覆盖等未被当前授权承接的部分继续 **pending**，不自动重启旧 M3。

## 本机、原评测及部署资源

[本机清单](https://github.com/LinsRock/unspun/blob/eb5b19f749c8316174e9cc5f6e838d7bbb0aec85/docs/acceptance/cl-00/local.json)、[预览绑定](https://github.com/LinsRock/unspun/blob/eb5b19f749c8316174e9cc5f6e838d7bbb0aec85/docs/acceptance/cl-00/preview-processes.json)、[外部证据](https://github.com/LinsRock/unspun/blob/eb5b19f749c8316174e9cc5f6e838d7bbb0aec85/docs/acceptance/cl-00/external-evidence.json)、[逐库规模](https://github.com/LinsRock/unspun/blob/eb5b19f749c8316174e9cc5f6e838d7bbb0aec85/docs/acceptance/cl-00/local-database-details.json)区分可重建缓存与唯一材料；处置登记为每条补上建议/理由/恢复入口。

| 对象 / 环境 | 实测 | 活跃依赖、建议与后续任务 |
| --- | --- | --- |
| 本机 Git | 26 worktrees（含 main/本轮），74 本地分支；worktree `du` 合计 4,087,586,816 B | 24 个历史 worktree 均无非忽略脏文件；非祖先提交常来自 squash，不能算未合并或可删。除活动项外留 pending，CL-03 检查会话、独有/忽略内容和 PR 精确 head 后再回收 |
| `r1-quality-candidate` / PID 23431 / 8113；`r1-runtime-accounting` / PID 40326 / 8114 | 两个 API health 成功 | keep：两者启动环境均指向**原评测库**及 `~/.cache/unspun-r1-content/quality-preview-config`，有显式各自源码路径；不对它们或原库做清理型测试 |
| `r1-reading-return` / PID 28813 / 5179 | Vite，代理 8113 | keep：仍运行；OS 进程检查不能证明其他会话已结束 |
| main `server/.venv` 与 `r1-production-rollout/server/src` | editable `.pth` 和 direct_url 均指向后者；8 个 server venv 链接、1 个 node_modules 链接 | keep 两端；不能移除 editable 目标。CL-00 Python 显式 `PYTHONPATH=$PWD/server/src`，已断言 `unspun`/models 来自本 worktree；未改 editable 或链接 |
| 212 项依赖/构建/测试缓存路径 | 按路径 `du`，见登记；包含 venv/node_modules/dist/pycache 等 | 依赖安装 keep，其余 pending；符号链接/共享块不相加估算释放量。CL-03 先处理导入和预览依赖 |
| uv、pnpm 三个全局缓存 | 4,147,085,312 / 1,404,489,728 / 3,487,076,352 B | pending：多项目共享；不把全部空间归本项目，不用全局 prune |
| 19 个 `~/.cache/*unspun*` 目录 | 343,676,226 逻辑 B；逐目录文件数/分配字节见清单 | 内容/原始响应/付费与验收证据可能独有，不能因路径叫 cache 删除；活动 quality 配置 keep，其余 pending → CL-03 |
| `/tmp/unspun-r0/raw`；main `docs/design/r0-reading/materials.local.json` | 原 raw 路径不存在；唯一找到的缓存 510,126 B | raw 恢复缺口 pending；正文缓存 keep，核验指纹后才可归档，不付费重抓/重生成 |
| 本机 Postgres | 48 库（含 postgres），目录截面 491,971,528 B；全部逐库只读计数，无查询失败 | 原评测/API 体验库/runtime preview keep，其余 pending。旧 `quality_eval` 还有 2,248 行已知费用、`quality_m3b` 93 行，名称含 test/quality 不表示可重建或可删 |
| 本机 Docker | Unspun 2 运行容器、5 相关镜像、3 相关/未知卷；daemon 73 cache records / 3.547 GB | [资源清单](https://github.com/LinsRock/unspun/blob/eb5b19f749c8316174e9cc5f6e838d7bbb0aec85/docs/acceptance/cl-00/local-resources.json)保留精确 ID；原 pgdata keep，匿名卷和无容器镜像 pending；其他项目只记录排除数量，构建缓存不可整体归属本项目 |
| VPS Docker | 11 容器（7 运行、4 停止），148 镜像；daemon 18.53 GB、报告可回收 11.83 GB；3 卷 | 当前/回退镜像和服务 keep；无容器引用的 139 镜像仍需核对回退/仓库恢复，不等于 delete。无 builder cache；精确 ID/tag/digest、挂载和日志配置见资源清单 |
| 四个停止观测容器 | [只读 tar 元数据](https://github.com/LinsRock/unspun/blob/eb5b19f749c8316174e9cc5f6e838d7bbb0aec85/docs/acceptance/cl-00/stopped-observations.json)：674 文件、41,328,665 逻辑 B；可写层合计 43,945,984 B | pending：原始响应仍在无持久挂载的容器层，先与已归档证据逐份比较；恢复用 `docker cp`，无需重启容器 → CL-03 |
| VPS `unspun_pgdata` / `unspun_backups` / 匿名 backup-image 卷 | `du` 198,072 / 638,548 KiB；匿名卷 docker 报 0 B，但有挂载 | keep；12 份 dump 合计 653,850,266 B。最新 10-19 dump 的 229 项 TOC 可列出，**未做隔离恢复**；14 天轮替保持，883 B 旧 dump 也未按大小/日期判删 |

非祖先/PR head 尚需对账的五个分支：`backup/r1-content-api-before-main-replay`、`docs/m3-admin-product-design`、`docs/t10-m2-closeout`、`feat/r1-production-rollout`、`test/r1-00b-technical-benchmark`，均 pending；最后一个非祖先数为 0 也不能代替用途核对。GHCR 全仓版本、异地备份存在性及云控制台资源未获完整枚举，生产主机容器日志字节未实测，均明确留未知；不影响 CL-01 的源码/服务边界。

## 业务数据与保留依赖

[生产截面](https://github.com/LinsRock/unspun/blob/eb5b19f749c8316174e9cc5f6e838d7bbb0aec85/docs/acceptance/cl-00/production.json)和[原评测截面](https://github.com/LinsRock/unspun/blob/eb5b19f749c8316174e9cc5f6e838d7bbb0aec85/docs/acceptance/cl-00/evaluation.json)逐表保存行数、heap/table/index/total 字节、外键、状态与 24h 写入时间分布，查询 SQL 随结果保存。[采集脚本](https://github.com/LinsRock/unspun/blob/eb5b19f749c8316174e9cc5f6e838d7bbb0aec85/docs/acceptance/cl-00/capture-db.py)只导入配置，**REPEATABLE READ / READ ONLY、限时 SELECT、最后 rollback**；没有 billing helper 初始化或提供方查询。其他本机库也使用同一只读方式。

| 生产精确对象/条件 | 行数 / total relation B | 建议与保留依赖 |
| --- | --- | --- |
| `articles`（legacy / r1） | 8,843 / 307；整表 77,283,328 B | keep：8,825 个事件引用、规范身份/当前材料/历史阅读；legacy 正文约 26.36 MB 不是可删量 → CL-04/05 |
| `events` / `event_viewpoints` / `digests` | 6,193 / 209 / 6；42,893,312 / 516,096 / 376,832 B | keep：事件 API、历史快照与离线契约；日报日期 10-10 至 10-15，旧生成停用不等于历史记录无用 → CL-04/06 |
| `content_materials` / `content_derivations` | 183 / 352；1,024,000 / 1,343,488 B | keep：169 个当前材料指针，版本/准入/审核/历史读；非当前且无派生仅部分候选，见下文 → CL-05 |
| `content_observations` / `fetch_logs` / `pipeline_runs` | 1,569 / 17,975 / 297；3,432,448 / 2,072,576 / 81,920 B | keep：来源诊断/身份/成本分母及旧失败；近 24h 新观测 1,389，旧轮次末次 10-15，不以年龄删 → CL-05 |
| `pipeline_tasks` / `task_attempts` / `discovery_batches` | 589 / 609 / 67；1,220,608 / 368,640 / 491,520 B | keep：581 完成、8 失败任务仍有去重/费用/恢复依赖；配额键唯一，收据和 payload 引用可核对。24h 任务 259、尝试 270、收据 67，不能按终态清除 → CL-05 |
| `content_identities` / `content_urls`；reader/feedback/change 全表 | 324 / 353；reader_state 1、changes 14、当前反馈/兴趣 0 | keep：规范身份、可撤销反馈及空状态都有语义；逐表字节和其他外键均在清单，0 行不等于 schema 无用 → CL-05 |
| `llm_usage` / `billed_requests` / budget/carry/expense/fx 全表 | 18,880 / 230；2,883,584 / 851,968 B | keep：生产总已知 $7.74501030（含旧链路），当前请求未知/未结预留 0；responded 行的历史 reserved 字段不可当现存预留。账务/审计零行表也保留 |

原评测 **12,064,435 B**：24 内容/材料、89 派生、401 物理请求、394 已知账目 **$0.3690100**、7 未知预留 **$0.484867**，两笔 settled-without-result 和历史失败全部保留；生产 $13.50、累计评测 $1.50 及原模型/来源/配额不变。观测没有手动触发处理或付费；生产自然运行持续计费，不能把本次与上次观察间的增量说成 0。

CL-05 的部分谓词为：`content_materials m JOIN articles a ON a.id=m.article_id WHERE a.current_material_id IS DISTINCT FROM m.id AND NOT EXISTS (SELECT 1 FROM content_derivations d WHERE d.material_id=m.id AND d.article_id=m.article_id)`，实测 **7 行、29,363 逻辑 B**；尚未排除任务 JSON、冻结/外部材料等引用，故 **pending**。另有 3 个相同文本指纹组、4 额外行，也不等于重复身份或可删副本。无全库删除谓词、统一 N 天期限或 schema 删除提案；CL-05 后续据读取/增长/恢复成本定规则，并待 R2-11 执行。**推荐窗口到期与存储处置分别判断**，合格历史详情、旧知识、失败反例及未知费用均在保护范围。

## 验证与接续

采集工具是本次固定范围的元数据/SELECT 脚本：[仓库/本机](https://github.com/LinsRock/unspun/blob/eb5b19f749c8316174e9cc5f6e838d7bbb0aec85/docs/acceptance/cl-00/capture-repo-local.py)、[Docker](https://github.com/LinsRock/unspun/blob/eb5b19f749c8316174e9cc5f6e838d7bbb0aec85/docs/acceptance/cl-00/capture-resources.py)；不引入清理命令或通用治理框架。文档链接、当前/历史状态、冻结哈希、登记完整性、差异格式和 CI 范围的结果见[验证记录](cl-00/validation.json)。本批没有页面/后端行为修改，不对生产/原评测库运行应用测试。PR、CI 与合并以本批 PR 的必需检查和最终交接为准；没有运行时发布。

接续只启动 **CL-01**：按 4 文件 + 4 局部动作及测试/文档编辑实施，保留全部共享依赖和当前消费者；CL-02 的历史索引、CL-03 的开发资源、CL-05 的数据候选各用本清单复核。当前 pending 项有明确归属，不阻止已明确的专属入口退役，也不授权顺手执行其他清理或 R2-04+/R3。
