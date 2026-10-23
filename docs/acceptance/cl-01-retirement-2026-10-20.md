# CL-01 旧 worker 退役 · 2026-10-20

**CL-01 已完成并实际部署核对；范围仅 CL-01。** 本地完整回归、隔离部署/回退及 PR/主干 CI 均通过。最新 `origin/main` 基线 `9ae42c4`，独立分支 `chore/cl-01-retirement`，worktree `~/.config/superpowers/worktrees/unspun/cl-01-retirement`。先读 CLAUDE、决策、清理板及 CL-00 报告/处置登记。新建独立 Python venv，确认 `unspun`、models、r1-worker 均导入本轮源码，不改其他 worktree 的 editable 或活动预览。

## 删除与保留

按 [CL-00 精确清单](cl-00-inventory-2026-10-20.md)删除四文件：`pipeline/main.py`、`pipeline/fetcher.py`、`test_pipeline_main.py`、`test_fetcher.py`（合计 12,661 B）。移除基础/生产 Compose 的 `services.worker`、部署脚本 `--scale worker=0`、本地旧注释；更新相应部署测试和当前启动说明。历史源码链接改为固定 `dc7c173…` 提交，保留历史事实，不改 CL-00 原始登记或冻结证据。

[引用复核](https://github.com/LinsRock/unspun/blob/eb5b19f749c8316174e9cc5f6e838d7bbb0aec85/docs/acceptance/cl-01/reference-check.json)确认 CL-00 至最新 main 没有 server/deploy/config/CI 代码变化，32 个传递依赖逐字节相同，专属导入只来自已删除文件。`r1_worker.py`/`r1_runtime.py`、全部共享模块及 API/评测调用保留；摘要、聚类、评分、观点、修复交 CL-04，日报及读取契约交 CL-06。不做符号级顺手清理。

部署保留固定镜像复用、DB→目标镜像迁移→预算/预检→启动→目标版本健康检查、中断身份保护与 `--remove-orphans`。移除部署成功后的自动 `docker image prune`，落实本批不清理镜像、保留固定回退资源的要求。没有清理已有数据库、镜像、worktree、业务数据、来源、配额、模型或预算。

## 验证与回退范围

数据库回归使用新建隔离库 `unspun_cl01_regression_20261020`；生产与原评测库仅 SELECT、READ ONLY，最后 rollback。付费、外部源 HTTP 均 mock；真实 Docker 另建随机项目及新卷，用一条 mock RSS 元数据证明受控 worker 领取/完成任务。隔离 fixture 的来源、key、网络和端口仅写入本机 `~/.cache/unspun-cl01-isolation-v4` 副本，不进入生产配置；测试后仅停止本轮容器，保留本轮库/卷与镜像。

[基础/本地真实栈](https://github.com/LinsRock/unspun/blob/eb5b19f749c8316174e9cc5f6e838d7bbb0aec85/docs/acceptance/cl-01/isolated-base-local.json)通过健康、停止→启动和重启；默认不创建受控 worker。原文件的[三种 Compose 渲染](https://github.com/LinsRock/unspun/blob/eb5b19f749c8316174e9cc5f6e838d7bbb0aec85/docs/acceptance/cl-01/compose.json)另核对无 legacy 服务，生产仍仅发布 `127.0.0.1:8080`、受控 worker 为 1。

[生产组合及故障结果](https://github.com/LinsRock/unspun/blob/eb5b19f749c8316174e9cc5f6e838d7bbb0aec85/docs/acceptance/cl-01/isolated-production.json)通过：真实预算初始化/预检→受控 worker 启动并完成 1 个 mock discovery 任务、停止→启动、API/web/受控 worker 重启；带 legacy service 标签但从未启动、仅 `sleep` 命令的 inert orphan 被 `--remove-orphans` 移除。全部 `llm_usage` 和 `billed_requests` 行数为 0，外部 HTTP fixture 对未登记请求直接抛错。

回退沿用退役后的脚本与 Compose：固定 server **`6f4fe4ff38c0b109f5d4648cddda0d4ae476fb93`**、web **`8dd144bc6cf5775e5dfe881cbdc50472bedb6486`** 退出 0，目标健康/schema `000017` 正确，随后省略两个镜像变量仍成功复用实际运行的固定引用；再切回本轮源码镜像成功。旧 server **`43150075d33e17298a21bfa909fac578f5d511d9`** 头为 `000016`，在原 `000017` 隔离库上报 `Can't locate revision identified by '000017'`、退出 255，预算/服务启动未执行，API/受控 worker 原容器 ID 不变。它不在直接回退支持范围；其他旧镜像未验证，不能推断兼容。没有降级或改写 schema/业务数据造证。

真实故障注入另证：迁移创建 marker 后抛错回滚；迁移 `pg_sleep` 中 SIGTERM 返回 143，校验 owner 后移除本次 one-off，schema 仍 `000017`、marker 不存在、消费者未创建；预算观察 503、预检缺 key 均在启动前失败。旧版本健康响应不能满足目标版本检查，部署返回失败，不伪报成功。命令日志保留在[逐场景日志](https://github.com/LinsRock/unspun/tree/eb5b19f749c8316174e9cc5f6e838d7bbb0aec85/docs/acceptance/cl-01/runtime-logs/)；脚本为本批一次性 [verify-retirement.py](https://github.com/LinsRock/unspun/blob/eb5b19f749c8316174e9cc5f6e838d7bbb0aec85/docs/acceptance/cl-01/verify-retirement.py)、[HTTP mock](https://github.com/LinsRock/unspun/blob/eb5b19f749c8316174e9cc5f6e838d7bbb0aec85/docs/acceptance/cl-01/mock-http.py)，不接入生产。

[镜像/环境](https://github.com/LinsRock/unspun/blob/eb5b19f749c8316174e9cc5f6e838d7bbb0aec85/docs/acceptance/cl-01/isolation-environment.json)区分 arm64 当前源码测试镜像与从生产缓存只读导出的真实 amd64 固定镜像；后者在本机模拟执行，正式 amd64 构建/部署另以 CI 核对。初次镜像构建的用户权限失败、`/tmp` 未共享造成的无效故障结果、验证脚本读取非部署场景日志失败、internal bridge 端口转发/空 feed fixture 问题分别留证并修正测试环境，没有改业务代码迁就测试，也不把这些失败算验收通过。

完整验证：[validation.json](cl-01/validation.json)。后端基线 **946** 项、删除 6 项专属测试后 **940** 项通过，0 跳过；Ruff/format/Pyright、旧 40 案例排序通过。部署 **18** 项、CI 范围 **11** 项通过；前端 **101** 项、lint/typecheck/build/PWA，以及由原路径分类器要求的存档原型 build 通过；没有页面改动或新增用户体验结论。冻结 **27/27** 按登记 revision 核验，v1/scan v2/candidate v3、空评分、CL-00 原始证据及 config 字节均未改。

## 部署、费用与未决项

[PR #109](https://github.com/LinsRock/unspun/pull/109) 于 `2026-10-20 06:09:43 UTC` 合并为 **`d72861bf854465a7a1107d149fad82dfe50281bb`**（实现提交 `87121cf`）。[PR CI](https://github.com/LinsRock/unspun/actions/runs/39378533063) 和[主干 CI/发布](https://github.com/LinsRock/unspun/actions/runs/39378805306) 全部成功，[任务/步骤记录](https://github.com/LinsRock/unspun/blob/eb5b19f749c8316174e9cc5f6e838d7bbb0aec85/docs/acceptance/cl-01/main-ci.json)确认实际执行 `Deploy`，不是跳过发布；[PR 元数据](https://github.com/LinsRock/unspun/blob/eb5b19f749c8316174e9cc5f6e838d7bbb0aec85/docs/acceptance/cl-01/pr.json)及[PR 检查](https://github.com/LinsRock/unspun/blob/eb5b19f749c8316174e9cc5f6e838d7bbb0aec85/docs/acceptance/cl-01/pr-ci.json)保留。

`2026-10-20 06:15–06:16 UTC` 的[运行探针](https://github.com/LinsRock/unspun/blob/eb5b19f749c8316174e9cc5f6e838d7bbb0aec85/docs/acceptance/cl-01/postdeploy-runtime.json)、[实际服务/部署文件审计](https://github.com/LinsRock/unspun/blob/eb5b19f749c8316174e9cc5f6e838d7bbb0aec85/docs/acceptance/cl-01/deployment-audit.json)与[交付断言](cl-01/delivery.json)确认：legacy worker **所有状态 0**、受控 worker **运行 1**；API/受控 worker 使用同一固定 `d72861b…` server，web 也为本次固定 `d72861b…`。APP_VERSION/health 正确，82 个 Python 文件、四份配置、六份部署文件逐字节匹配，schema **000017**，原两索引实存，唯一发布端口仍为 **127.0.0.1:8080**。API/受控 worker 没有 fixture/bind mount；[前](https://github.com/LinsRock/unspun/blob/eb5b19f749c8316174e9cc5f6e838d7bbb0aec85/docs/acceptance/cl-01/predeploy-boundaries.json)/[后](https://github.com/LinsRock/unspun/blob/eb5b19f749c8316174e9cc5f6e838d7bbb0aec85/docs/acceptance/cl-01/postdeploy-boundaries.json)的实际模型、`$0.40/24h`、八路运行阶段和整个来源配置指纹相同，新镜像的两个旧模块已不存在。正常 CI 部署以外未手改生产。

[读取前](https://github.com/LinsRock/unspun/blob/eb5b19f749c8316174e9cc5f6e838d7bbb0aec85/docs/acceptance/cl-01/predeploy-reading.json)/[后](https://github.com/LinsRock/unspun/blob/eb5b19f749c8316174e9cc5f6e838d7bbb0aec85/docs/acceptance/cl-01/postdeploy-reading.json)各 **108** 个公开对象，集合及推荐/最新前两页相同，停源 NYT 404、READ ONLY 重放不创建任务。这是部署代码路径核验，不冒充外部鉴权浏览器或新的用户体验验收。

[受保护生产前](https://github.com/LinsRock/unspun/blob/eb5b19f749c8316174e9cc5f6e838d7bbb0aec85/docs/acceptance/cl-01/predeploy-protected-production.json)/[后](https://github.com/LinsRock/unspun/blob/eb5b19f749c8316174e9cc5f6e838d7bbb0aec85/docs/acceptance/cl-01/postdeploy-protected-production.json)的 legacy articles、旧轮次与日报整行哈希相同，来源所有权/预算策略不变。生产旧摘要积压仍有 8,825 个待处理、18 个失败上限对象；本批不处理、不删除、不补造完成状态。[原评测前](https://github.com/LinsRock/unspun/blob/eb5b19f749c8316174e9cc5f6e838d7bbb0aec85/docs/acceptance/cl-01/predeploy-protected-evaluation.json)/[后](https://github.com/LinsRock/unspun/blob/eb5b19f749c8316174e9cc5f6e838d7bbb0aec85/docs/acceptance/cl-01/postdeploy-protected-evaluation.json)的全部审计查询结果相同：已知 **$0.3690100**、七笔未知预留 **$0.484867** 均保持；生产仍 $13.50、原累计评测 $1.50、总执行上限 $15，不释放任何未知预留。

本批新增付费测试/评测 **$0**，手动生产任务 **0**。自然生产在 `05:54:59.711032–06:15:30.015220 UTC` 的已知费用由 **$7.74501030** 增至 **$7.75298420**，真实增量 **$0.00797390** 单独记录；生产未知/未结预留截面为 0。这是观察期间原受控运行的费用，不归零、不并入 mock 测试费，也不承诺未来自然费用不变。

本轮隔离项目仅停止，库/卷、镜像、worktree 保留；[资源核对](https://github.com/LinsRock/unspun/blob/eb5b19f749c8316174e9cc5f6e838d7bbb0aec85/docs/acceptance/cl-01/retained-resources.json)确认原四个停止观测容器及三份固定回退镜像引用仍在，没有顺手清理。本批部署证据以纯文档补录 PR 合入，后续文档提交不等同运行版本。

CL-02–06、R2-04+、R3 均未执行；备份恢复、旧历史失败根因、冻结原始材料缺口、用户空评分等原 pending 继续留在原任务，不由本批冒充结案。
