# T7 日报生成与 API 实施计划

**Goal:** 按已批准的设计生成过去 24h 热度前 10 个事件的日报，支持最新与历史读取。

**Architecture:** 现有 worker 每轮开始查询当天是否已生成；复用事件输出结构保存 JSON 快照，LLM 仅写导语。数据库沿用 T4 表，无需迁移。

**Tech Stack:** Python、SQLAlchemy/Postgres、Pydantic、FastAPI、pytest。

## 1. 配置、生成与调度

- [x] 先在 `server/tests/test_digest.py` 添加配置、窗口排序、快照、同日替换、空日报、失败记账与时区边界测试。
- [x] 运行 `uv run pytest tests/test_digest.py`，确认由于日报实现缺失失败。
- [x] 在 `core/params.py` 新增 digest 配置和时区校验；`config/scoring.yml` 写入 8 点、上海、top 10；`core/config.py` 新增 digest_model。
- [x] 将事件序列化抽为 `api/events.py` 中可复用函数；在 `pipeline/digest.py` 实现候选 SQL、快照生成、导语验证、日报 upsert 和当天调度。
- [x] 运行目标测试确认通过。

## 2. API 与 worker

- [x] 在 `server/tests/test_digest_api.py` 添加最新、历史、空库、无此日期、非法日期与快照返回测试；添加 worker 失败隔离与执行顺序测试。
- [x] 运行对应测试确认失败。
- [x] 新建 `api/digest.py`，注册 latest 与 date 路由；在 `api/app.py` 注册 router；在 `pipeline/main.py` 每轮开始调用日报阶段，失败不阻断其余阶段。
- [x] 运行目标测试确认通过。

## 3. 验证、评审与交付

- [x] 在本地迁移后的 Postgres 上执行测试，确认数据库测试没有跳过。
- [x] 运行 `uv run ruff check .`、`uv run ruff format --check .`、`uv run pyright`、`uv run pytest`。
- [x] 评审差异与需求覆盖，处理发现的问题。
- [x] 在 `docs/tasks/m2.md` 登记本地验收结果与 T10 七天生产观察待办；保留 D-012 页面体验规则。
- [x] 提交单任务分支，按项目模板创建 PR 并确认 CI 状态；不自动合并。PR：[#39](https://github.com/LinsRock/unspun/pull/39)。
