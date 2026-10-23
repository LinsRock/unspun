# R1-01 运行诊断与迁移启动安全

日期：2026-10-16。任务：[R1-01](../tasks/r1.md)。本记录不作为自动发现、来源发布、G1 或 R1 用户验收通过的证据。

## 目标环境只读复核

05:07:49 UTC，通过已有 `ssh unspun` 连接读取容器状态、镜像信息、数据库版本和回环健康接口，没有恢复旧 worker、写业务数据或修改生产容器。

| 项目 | 实际结果 |
| --- | --- |
| API/web 版本 | `a00a4986e4cc28fe1eb9333f3d33e8bcb76e69ea`（PR #64） |
| API 镜像 ID | `sha256:06215bd388daa6e90f2441c0b9f160631a53c87620bd04c760b3c2eb6c052e32` |
| 数据库 | PostgreSQL 17.11，Alembic `000010` |
| 历史数据计数 | articles 8843、events 6193、digests 6、llm_usage 18650；只读计数，不复制正文或改写旧日报 |
| 旧 worker | `docker ps -a` 无该容器；`docker logs --tail 100 unspun-worker-1` 返回 `No such container` |
| 旧镜像 | `dfa212c494de8ccf05eb6359a1c864bf23479659` 仍在；digest `sha256:6ea4456a3fc46b8d93e968ff16f5f8fe40b1fb3f4eca53e9bd4461b7314afc42` |
| 生产工具与资源 | Docker Compose v5.6.0；RSSHub 仍为 `2026-10-09`、512 MiB；备份运行，宿主入口仍为 `127.0.0.1:8080` |
| API 健康 | `status=ok`、`database=ok`、version 为上述 PR #64 提交 |

历史 [R0 记录](../research/r0-2026-10-15/runtime-environment.json)只有退出码 1 和退出时间；[停用记录](legacy-worker-disabled-2026-10-16.md)记有重启计数 37。留存的本机 `runtime-container.txt` 也仅有退出状态，没有异常栈。容器已经被零副本部署移除，现有证据不足以认定退出/重启根因；不将迁移顺序风险推断成旧 worker 的已证实根因，不启动它补日志，也不宣称修复旧循环。

账本只读复核：停用时间 `2026-10-16 03:52:09+00` 之后记录为 0 笔、已知金额 $0；最近一笔为 `2026-10-15 06:37:53.879685+00`。这不证明历史所有外部调用均已入账，也不宣称供应商没有未结费用。本任务不发起模型调用。

## 部署边界

[脚本](../../deploy/deploy.sh)要求明确目标镜像和版本，依次执行：

1. 获取尚未缓存的固定版本镜像；不在每次部署隐式更新 RSSHub。
2. 只启动数据库，以 `up -d --wait --wait-timeout 120 db` 等待健康。
3. 用目标 API 镜像执行 `run -T --rm --no-deps --name <project>-migration api alembic upgrade head`，不先启动 API 或其依赖。
4. 仅迁移退出 0 后执行服务启动，并显式传入 `--scale worker=0`；未来 R1 消费者还需各自的门槛和部署 PR。
5. 回环检查同时匹配健康状态与目标 `APP_VERSION`，不能用旧健康 API 误报目标发布成功。

拉取、DB 就绪或迁移失败时立即退出，不进入目标服务启动；已有 API/web 保持原实例。迁移期间收到 SIGTERM/SIGINT 时，脚本停止迁移客户端并校验部署身份标签后清理本次命名容器，退出 143/130，不继续启动服务；不会清理其他部署的迁移容器。CI 生产部署 job 串行执行且不取消在途部署；固定迁移容器名拒绝重叠迁移。

SIGKILL、宿主掉电和 Docker daemon 失联无法由 shell trap 保证清理；可能留下 one-off 容器，不能把它当成功迁移。重跑如遇容器名冲突会失败关闭，先只读检查容器/数据库，再按正常修复 PR 处理；不得绕过迁移或启动旧循环。迁移成功后再中断可能留下新 schema 与旧 API，因此所有 R1 迁移仍须增量兼容；后续任务逐次验证。

## 兼容与回退

本 PR 不改变 schema，当前兼容范围为 `000010`。`a00a498`、`1a151d4`、`6510ba3` 和 `dfa212c` 的源码迁移头均为 `000010`；回退采用当前已修复的部署配置/脚本和经过核对的该范围镜像，仍强制 worker 零副本。不可把旧的先启动后迁移脚本一并回退。

操作形态与 CI 相同：指定 `SERVER_IMAGE=ghcr.io/linsrock/unspun-server:<sha>`、`WEB_IMAGE=ghcr.io/linsrock/unspun-web:<sha>`、`APP_VERSION=<sha>` 后运行当前 `bash ~/unspun/deploy/deploy.sh`。先确认镜像包含当前数据库迁移头及 API 兼容证据。早于当前迁移头的镜像可能无法解析数据库 revision，必须失败关闭，不能承诺任意旧镜像可直接回退。后续增量迁移不得降库、删表或重写历史来配合回退；也可通过经 PR 关闭 R1 阶段保留当前兼容 API。

## 验证记录

真实 Docker 验证于 05:24:09–05:26:41 UTC 完成，见[逐项结果](https://github.com/LinsRock/unspun/blob/eb5b19f749c8316174e9cc5f6e838d7bbb0aec85/docs/acceptance/r1-01/isolated-startup.json)。三个 Compose project 各自新建空卷、网络和数据库，分别使用回环 18081/18082/18083；未挂生产卷，也不使用默认本地开发库。结束后仅清理这些专用 project/卷，原本地 db/RSSHub 保持运行。

本机直接拉 GHCR 目标镜像返回 unauthorized；完整 Dockerfile 的基础镜像元数据获取未完成；只读 SSH 镜像导出因链路速度未继续使用。隔离测试改用现有 Python 3.12.15/arm64 缓存基础镜像，复制当前 server 源码、所有迁移与 config，并通过 `uv export --frozen --no-dev --no-emit-project` 和跨平台 wheel 安装补齐 **当前锁文件全部 55 项运行依赖**。[隔离环境版本清单](https://github.com/LinsRock/unspun/blob/eb5b19f749c8316174e9cc5f6e838d7bbb0aec85/docs/acceptance/r1-01/isolation-environment.json)记录锁文件与镜像指纹；SQLAlchemy 2.1.4、Alembic 1.20.0、Pydantic 2.13.5；Postgres/pgvector 17，RSSHub 版本与内存约束不变。测试镜像 `unspun-server:r1-01-isolated` 的 ID 为 `sha256:981b88c4b674a29b949135e546093de848c4461c4eb89cba0a6833e8c4750e8f`；web 使用本机既有 Caddy 镜像，仅验证代理健康，未把旧静态页面算新页面验收。本 PR 不改 server/web 源码；生产 linux/amd64 的正式镜像仍由 CI 正常构建与部署，不以本机 arm64 结果冒充生产平台验证。

[首轮失败](r1-01/first-environment-failure.json)保留：初用 M0 缓存镜像只复制当前源码，因缺 pgvector 退出 1；没有进入 API/web 启动。之后才按锁文件补齐依赖，没有为消除环境失败修改业务代码。失败和中断场景均先把各自专用库迁到 `000010`，随后只在隔离镜像中挂入 `r101_fault` 迁移：创建测试标记表后抛错，或进入 `SELECT pg_sleep(120)` 再向部署脚本发 SIGTERM。两者均保留 `000010`、标记表不存在、API/web 未创建；移除故障 fixture 后在同一专用库重跑成功。

可复用验证入口为 [verify_startup.py](../../deploy/tests/verify_startup.py)，只接受新证据目录，使用随机项目名；镜像须已准备好且含 `000010`。执行形态：

```sh
python3 deploy/tests/verify_startup.py \
  --server-image unspun-server:r1-01-isolated --web-image unspun-web:dev \
  --code-revision a00a4986e4cc28fe1eb9333f3d33e8bcb76e69ea \
  --evidence-dir /absolute/docker-accessible/new-evidence-directory
```

通用入口于 05:27:45–05:30:16 UTC 再次完成全部三个场景，见[复现结果](https://github.com/LinsRock/unspun/blob/eb5b19f749c8316174e9cc5f6e838d7bbb0aec85/docs/acceptance/r1-01/isolated-startup-reproduction.json)；新随机项目名、专用卷与原本地库隔离。审查修复后于 05:37:11–05:39:42 UTC 再以当前脚本完成[最后一轮真实复测](https://github.com/LinsRock/unspun/blob/eb5b19f749c8316174e9cc5f6e838d7bbb0aec85/docs/acceptance/r1-01/isolated-startup-reviewed.json)，三场景及故障后重跑全部通过。

| 检查 | 实际结果 |
| --- | --- |
| 后端基线 | 显式新建 `unspun_r1_01_20261016`，从空库迁移到 `000010`，631 项通过，无跳过 |
| 后端静态检查 | Ruff、格式检查、严格 Pyright 通过 |
| 旧标准排序 | 40 事件，`ready=true, passed=true, issues=0` |
| R1 输入登记 | `registration_valid=true, technical_ready=false`；用户质量仍待最终验收 |
| 脚本故障注入 | 10 项 unittest 通过（7 项部署边界、3 项验证进程），覆盖正常顺序、三类失败、目标镜像缺失、旧健康版本误命中、SIGTERM、其他部署容器保护、交互终端输出及超时子进程清理；不是 Docker/DB 集成的替代 |
| 真实隔离栈 | 正常退出 0，故障退出 1，中断退出 143；两次故障后重跑退出 0；正常 API 重启后目标版本/DB 健康；均无 worker、调用行数为 0 |
| 独立代码审查 | 两轮 `codex review --uncommitted` 完成；先修复跨部署清理，再按两项 P2 修复 Compose 2.34 交互终端 TTY 与验证超时后进程残留，10 项回归通过。审查子进程无 Docker socket 权限，真实 Docker 由本会话独立执行，不计审查环境已执行 |

以上不启用 R1 采集或付费处理；新来源窗口、材料与消费由 16/17 另证。所有临时数据库/容器与生产隔离，不能用 API 健康替代真实新条目。
