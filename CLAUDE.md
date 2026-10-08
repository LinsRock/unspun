# Unspun · 个人情报站

只给一个人用的情报聚合站：抓取中英文信息源，AI 聚类、评分、对比观点，打破信息茧房。
需求见 `docs/requirement.md`，里程碑与验收标准见 `docs/roadmaps.md`。当前阶段：**M0 工程骨架**。

## 架构

```
浏览器 → Cloudflare Access(登录) → Cloudflare Tunnel → VPS
  VPS 上 cloudflared 指向 127.0.0.1:8080 (web 容器,唯一发布端口)
  web(Caddy: 静态文件 + /api/* 反代) → api(FastAPI) → db(Postgres+pgvector)
  worker(流水线,与 api 同镜像不同命令) → db
```

## 目录

| 目录 | 内容 |
| --- | --- |
| `server/` | Python 单项目：`unspun.api`（FastAPI）、`unspun.pipeline`（流水线）、`unspun.core`（配置/日志/DB，两者共用） |
| `web/` | React SPA：Vite + TypeScript strict + Tailwind，oxlint + Vitest |
| `config/` | 信息源清单、权重、评分参数（日常调整只改这里，不改代码） |
| `deploy/` | Dockerfile、Compose（base + local/prod 覆盖层）、Caddyfile、deploy.sh |
| `docs/` | 需求文档、路线图（任务书，改需求先改这里） |

## 常用命令

```bash
# server/ 下
uv sync                 # 装依赖
uv run ruff check . && uv run ruff format .
uv run pyright          # strict 模式
uv run pytest
uv run alembic revision --autogenerate -m "..."   # 新建迁移
uv run uvicorn unspun.api.app:app --reload        # 本地跑 API (:8000)

# web/ 下
pnpm install
pnpm lint && pnpm typecheck && pnpm test
pnpm dev                # 本地开发 (:5173, /api 代理到 :8000)

# 仓库根目录：本地全栈（db + api + worker + web）
docker compose -f deploy/compose.yml -f deploy/compose.local.yml up --build
```

## 开发流程

- 一律走分支 + PR，CI 全绿才能合并；合并到 main 自动构建镜像推 GHCR 并部署到 VPS。
- 部署由 `.github/workflows/ci.yml` 的 deploy job 完成：cloudflared SSH 进 VPS 跑 `deploy/deploy.sh`（pull 镜像、up、跑迁移、health 冒烟）。
- 环境变量统一 `UNSPUN_` 前缀，定义在 `server/src/unspun/core/config.py`。

## 禁止事项

- 密钥不进仓库、不进 CI 日志。生产密钥只存在 VPS 的 `~/unspun/.env`。
- 数据库结构变更必须走 Alembic 迁移；涉及删表、删列的迁移需要用户确认后才能合并。
- 不要在生产服务器上手动改容器或数据，一切变更走 PR。
- 不要发布除 `127.0.0.1:8080` 之外的任何端口到宿主机（生产）。
- 修改提示词或评分逻辑（M3 起）必须跑标准事件集评测，不达标不合并。
