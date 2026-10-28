# CL-03 本机开发残留回收

2026-10-27，从最新 `origin/main 4042f20` 新建 `chore/cl-03-local-cleanup`。依据 [D-031](../decisions.md#d-031--2026-10-19--分阶段安排旧链路文档及无用过时数据清理)、[清理任务板](../tasks/cleanup.md)及 [CL-00 历史盘点](cl-00-inventory-2026-10-20.md)，本批已实际回收以下本机资源。精确对象、原 head、字节、保留/待定理由与恢复版本见[处置登记](cl-03-disposition-2026-10-27.json)；旧盘点没有直接充当删除名单。

**最新排期：R2-11 暂缓，8/12 次与全部结果、脚本及原失败保持；不继续探测、不改变现网。** 待续资源及 [PR #143 固定交接](https://github.com/LinsRock/unspun/blob/6a1592cd8e32157860aeebf6810b3a8c6c4c2a44/docs/acceptance/r2-11-reading-enablement-2026-10-26.md)全部保留，旧“到时执行”说明须服从此次暂缓。CL-04/05/06、R3 未实施。

## 实际回收与计量

| 对象 | 实际结果 | 计量 |
| --- | --- | --- |
| 旧 worktree | 15 个；34 → 19（均含本批工作区） | 2,616,478,378 逻辑 B，包含内部依赖、缓存和构建产物，不再另加一次 |
| 本地分支 | 上述目录的 14 个分支；111 → 97 | 精确 head 与已合并 PR 匹配、合并提交在主干可达，远端同名 head 保留；没有删除远端或改写历史 |
| 重复排序导出 | 8 份 | 2,031,216 逻辑 B；均与保留的 `docs/evaluations/r1/legacy-regression-v1.json` 相同 |
| 旧镜像依赖构建目录 | `~/.cache/unspun-r1-01/image/packages` | 206,540,924 逻辑 B；相邻锁定 requirements、Dockerfile、失败与验证结果保留 |
| 一次性空测试库 | 16 个；100 → 84 | 删除前 `pg_database_size` 合计 190,226,672 B；业务/费用/预留行均 0，仅 16 条 schema 版本行，不删任何保留库的表/列 |

文件总计 **2,825,050,518 逻辑 B（2.63 GiB）**。不跟随符号链接；按 `(device,inode)` 跨对象去重，目录内部项目不重复计算；相应 `st_blocks` 为 3,627,732,992 B，**不是实际释放量**。APFS 克隆/快照及其他进程可能影响宿主读数。

删除窗口内宿主可用空间从 **171,401,531,392 → 173,013,815,296 B**，实测净增 **1,612,283,904 B（1.50 GiB）**。本机 Postgres 虚拟机内精确 16 个 OID 目录原分配合计 **193,212,416 B**；删除后 `base` 的 `du` 同量减少，VM 文件系统可用空间净增 **193,204,224 B**。宿主与 VM 数值、逻辑文件与数据库物理字节各自报告，**不相加**；未声称虚拟磁盘镜像已缩容。后续验证新建的三个专用库均已删除，不计作旧资源回收。

## 删除条件与保留范围

实时核对所有 34 个 worktree、111 个本地分支、100 个本机库；检查 Git 非忽略修改、全部忽略文件类别、精确 PR head/合并提交、OS cwd/打开文件、tmux/监听端口、editable 的 `.pth`/`direct_url`、跨目录符号链接、缓存脚本引用、Docker 挂载及数据库活跃连接。选中目录均无未提交或独有非生成文件。squash head 不是主干祖先时，以精确已合并 PR 和远端恢复 head 验证，不能单凭 `--merged` 推断。

使用逐路径 `git worktree remove --force`（仅放行已登记的可重建忽略内容），逐分支校验 head 后删除本地引用；单文件/单目录删除均来自固定名单。数据库每次删除前再次检查零连接及零业务行，使用本机 `DROP DATABASE`，没有 `FORCE`、连接终止或全局 prune。清理前计划、只读盘点和本地验证过程留 `/private/tmp/unspun-cl03-20261027/`；长期只保留本报告及必要处置登记，不提交运行日志或整机快照。

| 保留 / 待定 | 原因和状态 |
| --- | --- |
| main、R2-10、R2-11 工作区及依赖 | main 的共享 venv 已实际指向 main 源码，CL-00 的旧 rollout editable 关系已不存在，本批无需改写。预览各用独立 venv；8010/5178、8011/5179/4180 及四个 tmux 会话保持 |
| `r2-reading-rollout` 与三个 `~/.cache/unspun/r2-11-*` 目录 | PR #143 未合并；计数、旧脚本、加固脚本、全部首次结果与误回退记录字节保持；待续测试/阅读库即使为空也不删 |
| `r2-source-increments`、R2-04 冻结与本机缓存 | 保留全部观察/恢复入口；远端观察容器及生产资源本批未连接、未探测、未修改 |
| 其他 13 个保留的旧 worktree | 包含当前恢复脚本仍引用的目录、冻结/付费复现环境及尚未核清的旧预览用途，逐项见登记；不以已合并或进程已停止自动判删 |
| 84 个剩余数据库 | 真实付费评测、未知费用、当前/历史预览、R2-04/11 及用途未全核清的恢复/测试库均保留，登记逐库列名；9 个关键库逐表内容哈希不变 |
| 独有 / 未能对应已合并 head 的分支 | `backup/r1-content-api-before-main-replay`、`docs/m3-admin-product-design`、`docs/t10-m2-closeout`、`feat/r1-production-rollout`、`docs/r2-reading-rollout` 保留；其余未选中分支未动 |
| Docker、全局缓存及唯一材料 | 本机 50 个相关容器（1 运行）、10 个相关镜像、18 个项目命名卷及 4 个匿名挂载卷不删，停止层/回退用途待核；uv/pnpm 等共享缓存不归本项目回收。真实输出、未知凭证、paid-stop、原累计评测库、R0 唯一正文缓存全部保留 |

## 恢复与验证

- **worktree / 分支：** 登记保存完整 SHA、远端引用和原路径。用 `git worktree add -b <原分支> <原路径> <recovery_ref>` 恢复；原 detached `r2-scan-quotas` 用 `git worktree add --detach <原路径> <完整SHA>`。Git 对象和远端 head 可读；依赖按对应锁文件 `uv sync --frozen` / `pnpm install --frozen-lockfile` 重建，不依赖已删目录启动。
- **重复导出：** 从固定 `4042f20ddae82b9282e8c3b57c5c99bbcb430125:docs/evaluations/r1/legacy-regression-v1.json` 用 `git show` 恢复到登记路径；SHA-256 均为 `a20e6e062b84aef1299b8dfe5eef89d255644104442e033eaa1c2918564852d3`。冻结基准本身未删除、未改字节。
- **镜像构建目录：** 保留的 `image/requirements.txt`（带版本与 hash）和 Dockerfile 可重建 Linux aarch64 / Python 3.12 的 `packages` wheel 安装目录；不是独有源码或模型结果。当前开发及预览使用各自现有 venv，与该目录无导入/挂载依赖。
- **空测试库：** 在登记固定提交的独立源码下，新建同名本机空库，显式设置该库的 `UNSPUN_DATABASE_URL` 后执行 `python -m alembic upgrade <登记schema>`。11 个目标版本 `000009–000017 / 000020 / 000021` 已在专用库逐级重建，表集合与空数据核对通过。首次重建发现 `unspun_m3b_b2_test` 的旧 `000010` 多出空 `event_read_states`；追溯到合并前变体后，另用固定 `b32f51aadf4f5d34be1093be8f08b05af886c33e` 成功重建其旧表集合及 `unread_only`，登记使用该版本，不把相同 revision 号当相同 schema。
- **源码与启动：** main、最新 CL-03 源码、R2-04、R2-10、R2-11 的 `unspun`/API/models 导入路径均通过。CL-03 显式 `PYTHONPATH` 使用最新源码及保留的 main 依赖，不重绑共享 editable；临时前端依赖链接验证后已移除。新空库迁到 `000021`，清理前后健康/Reader 17 项均通过；清理后前端 **142 项通过**、TypeScript/正式构建和 Vite 源码变换通过，当前 API 实际启动健康。自建服务已停止，未重启保留预览。
- **保护核验：** main、R2-04/11 工作文件及项目缓存中 **5,142 个登记文件** SHA-256 相同；9 个关键本机库所有用户表内容哈希相同。R2-10 原健康/发现入口 HTTP 200；R2-11 仅核验本机进程、导入和已有文件，不运行观察器或读取 mixed。预算、paid-stop、未知预留、原失败及用户评分空值保持。

本批主动生成、embedding、付费重试、提供方查询与生产操作 **均 0**；不将原生产消费者的自然活动宣称为零。交付为纯说明文档，应用/配置/部署/冻结输入无改动；已复核处置名单、共享依赖、恢复路径及完整文档差异；104 个本地链接、产品验收勾选不变、差异格式、约定及 11 项 CI 路由检查通过，全部运行时检查/构建/发布选择为 false。[PR #144](https://github.com/LinsRock/unspun/pull/144) 已提交；[首轮 CI](https://github.com/LinsRock/unspun/actions/runs/40479794089) 的 `changes` / `required-checks` 明确因近期付款失败或 spending limit 未启动，非应用测试失败。2026-10-28 仓库已公开，Actions 已恢复；本次收口同步 #143 合并提交 `a0854c4` 并解决文档冲突，保留 R2-11 暂缓及全部实际回收事实。最终 head `0f6c07e` 的[必需 CI](https://github.com/LinsRock/unspun/actions/runs/40665094463) 实际通过，随后合并为 `f5db113`；不绕过检查、不触发部署，不重复清理或探测。
