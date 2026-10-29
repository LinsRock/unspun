# CL-04B · 生产镜像内容收敛

本批基于最新 `origin/main` **`82f8cef9a6079c4d22727b6a4412cc2a04c6ccf7`**，独立工作区 `~/.config/superpowers/worktrees/unspun/cl-04b-image`。只收敛生产构建输入和最终镜像文件，不移动共享函数、不升级依赖、不删除仓库测试或历史原件；完整 CL-04 仍未验收。前置事实与默认 1,368 项回归见 [CL-04A 交接](cl-04a-dead-code-2026-10-28.md#2026-10-29-默认回归覆盖恢复)。

## 必要运行文件清单

静态核对 API 路由注册、受控 worker 的显式 handler、迁移、预算管理、运维 CLI 及其导入；四个入口传递到 86 个模块，无运行模块反向导入 `unspun.evaluation`。另核对 R2-11 已登记接续/回退脚本，它们从镜像使用的运行包、`/app/src` 路径和 Compose 入口均保留，不运行这些脚本。保留完整共享包而不逐函数裁剪，业务源码与配置字节保持。

| 最终镜像路径 / 仓库来源 | 保留原因 |
| --- | --- |
| `/app/.venv` ← 原锁定生产依赖及 editable 安装 | 仍使用原 `uv sync --frozen --no-dev`；依赖组、版本、解释器及安装方式不变 |
| `/app/src/unspun/__init__.py`、`api/`、`core/`、`pipeline/` ← `server/src/unspun/`，共 91 个 Python 文件 | `unspun.api.app:app`、`python -m unspun.pipeline.r1_worker`、`python -m unspun.core.billing_admin`、`python -m unspun.pipeline.repair_grounding` 及共享依赖；保留旧阅读、日报及历史失败复现所需共享实现 |
| `/app/alembic.ini`、`/app/alembic/{env.py,script.py.mako,versions/*.py}`，共 24 个文件 | 原 `alembic upgrade head` 及完整 `000001`–`000021` 迁移链；部署和固定镜像回退顺序不变 |
| `/app/config/sources.yml`、`scoring.yml`、`media_groups.yml`、`r1-reader.yml`、`r2-hybrid.yml` | 来源/受控运行、旧评分/媒体组、内容阅读及混合排序的实际文件读取 |

应用、迁移和配置合计 **120 个文件、906,415 B**，不含依赖 venv。包元数据和 lock 仅用于 builder，不进入最终镜像；editable 的 `/app/src` 路径保持。`deploy/deploy.sh` 和 Compose 留在宿主，仍以目标镜像执行迁移、预算初始化/预检，再启动 API/受控 worker；没有新运维入口。

生产镜像排除 `server/tests/`（85 文件）、`server/eval/`（3）、`server/src/unspun/evaluation/`（23）、`server/typings/`（1）及构建元数据；不接收本机 `.venv`、隐藏环境文件、缓存、字节码、临时导出或其他未列入白名单的文件。生产专用 `deploy/server.Dockerfile.dockerignore` 不作用于独立的 `server/tests/Dockerfile`，也不限制源码挂载。全部原件继续留在仓库原路径，13 项 `legacy_batch` 仅分类，默认完整回归和固定 40 例排序入口不改。

## 验证与交付

本机在同一 checkout、相同 base 与锁定依赖下分别构建精简前/后镜像（arm64）；最终 120 个应用/迁移/配置文件与仓库和基线镜像哈希逐项一致，56 个已安装生产 distribution 的名称/版本一致，venv 逻辑大小同为 **244,734,237 B**。不裁剪第三方包或 builder 生成的依赖字节码。

| 同口径读数 | 基线镜像 | 最终镜像 | 变化 |
| --- | ---: | ---: | ---: |
| `/app` 非 venv 文件数 | 234 | 120 | −114 |
| `/app` 非 venv 文件逻辑字节 | 2,563,184 B | 906,415 B | −1,656,769 B（64.64%） |
| Docker Engine `image inspect .Size` | 120,865,750 B | 120,486,186 B | −379,564 B（0.314%） |

依赖占主要体积，以上是构建比较，不宣称回收了宿主或生产磁盘空间。镜像使用单独固定标签 `unspun-cl04b:{baseline,runtime-final}-20261029`，没有覆盖现用/回退标签。初版目录例外被污染样本查出会放入包内临时 JSON；最终改为仅文件例外。对包含 10 个合成环境文件、venv、缓存、字节码目录和临时导出的构建上下文复验，builder 输入精确为 120 个运行文件加 2 个构建元数据，最终镜像仍为原 120 个文件；所有污染文件均未进入。

最终镜像不挂源码，在新建的 `unspun-cl04b-20261029-smoke-final-db` / `unspun_smoke` 和专属 internal 网络上验证：全部 **91 个模块导入**、5 份配置的实际 loader、完整迁移至 `000021` 及重复执行、预算 CLI `status`、修复 CLI `--help`、真实 Uvicorn 启动及 `/api/health`、受控 worker `--check` 和有界启动/停止通过。真实 key 为空时预算预检仍以 2 退出；正向预检只用明确无效的合成 key 字符串和新库合成预算，重用初始化不查询提供方。来源下次调度设在隔离验证之后，未触发抓取或处理；结束后 `articles`、`pipeline_tasks`、`task_attempts`、`billed_requests`、`llm_usage` 均为 0。IPv4/IPv6 原生外连失败，无真实模型调用或提供方查询。

基线新隔离库先通过 13 项 mock，再默认执行 **1,368 项全部通过、0 跳过/排除**。独立测试镜像由原 `server/tests/Dockerfile` 重建，以当前完整源码只读挂载，在另一个新库 `unspun-cl04b-20261029-final-tests-db` / `unspun_test` 上重复空真实密钥、空库和 IPv4/IPv6 外网阻断预检，先 **13 项通过**，再默认 **1,368 项全部通过、0 跳过/排除**。固定 **40 例排序通过**（ready/pass true、issues 0）。Ruff、223 文件格式、Pyright（0 错误/警告）、CI 路由 11 项、部署安全 19 项和 Bash 语法检查通过；PR/CI 交付事实另补录。

差异及调用方审查覆盖 editable 导入路径、包内文件读取、全部迁移、预算初始化/预检/失败关闭、运维/回退、独立测试镜像及默认收集、容器用户/CMD/环境/端口、最终层和污染上下文边界，无未解决问题。最终仅改生产 Dockerfile、生产专用 ignore 和三份说明文档；业务源码、lock/依赖声明、测试正文/断言/marker、schema、运行 YAML、Compose、部署脚本、Web、R2 任务板及原验收/冻结输入均与基线一致。原登记 **635 份保护文件**逐项哈希保持，完整 CL-04 四项验收清单不改；84 个本地文档链接有效，`git diff --check` 通过。新增 ignore 作为既有分类器的未知构建输入走保守完整 CI，不缩减检查范围。

普通日志、逐文件哈希及本批新资源归属仅存 `~/.cache/unspun/cl-04b-image-20261029/`，不提交整套环境快照。

R2-11 继续 **8/12 暂缓**；预算、paid-stop、未知预留、冻结输入、R2-04/11 原件和已登记环境保持。当前及已验证回退镜像保留，不清除镜像或卷。真实模型付费、提供方查询、mixed 探测、生产数据清理、CL-06 和 R3 均为 **0**；本批完成后不自动扩大清理范围。
