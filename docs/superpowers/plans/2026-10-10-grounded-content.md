# Grounded Content Implementation Plan

> **For agentic workers:** Use subagent-driven-development sequentially; review each component and integrate before starting dependent tasks.

**Goal:** 摘要/观点有可检查的原文依据，差异分类保守，内容修改触发正确重生成，并通过固定样本评测。

**Architecture:** 共享证据校验模块 + JSONB 摘要元数据；观点 JSON 扩展，API/前端兼容旧快照；独立评测与显式修复入口。

**Tech Stack:** Python / SQLAlchemy / Alembic / pytest，React / Vitest，OpenRouter 现有模型。

## Task 1：摘要证据

Files: `server/src/unspun/core/grounding.py`, `models.py`, `pipeline/summarize.py`, `server/alembic/versions/20261010_000007_summary_grounding.py`, `server/tests/test_grounding.py`, `test_summarize_cluster.py`, `test_models.py`。

- [x] 先写引用跨文章、伪造年份、空证据、标题保底、有限正文、兼容旧数据和记账测试；`uv run pytest tests/test_grounding.py tests/test_summarize_cluster.py` 确认缺失行为失败。
- [x] 实现共享 normalize/quote/year/source-text 函数和增量迁移；摘要使用 facts+quote 输出，把有效 facts 拼为摘要并保存 summary_grounding。
- [x] `uv run alembic upgrade head && uv run pytest tests/test_grounding.py tests/test_summarize_cluster.py tests/test_models.py`；ruff/pyright，核对真实证据仅取传入文本。

## Task 2：观点证据/分类/指纹

Files: `server/src/unspun/pipeline/viewpoints.py`, `server/tests/test_viewpoints.py`。

- [x] 测试同 ID 内容改变、模型/版本改变、无修改跳过、跨源引用、额外年份拒绝、索引重映射、空比较缓存、调用预算；先运行观察失败。
- [x] 构造有发布时间与证据片段的提示，验证每条 evidence_quote；五种 kind 分类，允许空比较；指纹与候选发现内容/版本变化。
- [x] 运行全部观点单测与严格类型/格式检查；按批准的模型档位执行，记录实际生成输入。

## Task 3：API 与展示

Files: `server/src/unspun/api/events.py`, `server/tests/test_events_api.py`, `test_digest_api.py`, `web/src/api.ts`, `EventCard.tsx`, `DigestItem.tsx`, frontend tests。

- [x] 先补 JSON 可选字段与历史快照读取测试，以及原文依据/差异类型/历史未附证据/不安全外链的 UI 测试。
- [x] 兼容旧 JSON，保留重映射后的 kind；展示引文、有限信息和差异类型，移动端可展开，不增加无关导航。
- [x] lint/typecheck/test/build 与浏览器窄屏/暗色检查，提供本地体验。

## Task 4：固定评测与受控修复

Files: `server/src/unspun/evaluation/`, `server/tests/test_quality_evaluation.py`, `server/src/unspun/pipeline/repair_grounding.py`, `server/tests/test_repair_grounding.py`, `docs/evaluations/`。

- [x] 固定 30 案例输入/预期（生产五例 + 合成对照），测试指标对坏输出与全拒绝的区别，测试费用记录与修复 dry-run/失败回滚。
- [x] 评测 CLI 生成 JSON 报告，离线与真实模型结果明确区分；只在隔离数据库运行模型调用，预算/调用数有上限。
- [x] 实现受控按事件 ID 修复，更新依赖信息、重新评分/观点、保留历史日报和失败调用费用。
- [x] 相同样本比较旧/新真实输出，逐案复查失败和分类，记录指标、成本与限制。

## Task 5：交付

- [x] 更新 requirement/decisions/M2 任务说明与评测记录，不提前关闭 T10。
- [x] 全量后端/前端检查、迁移、独立规格与代码评审、生产构建浏览器检查。
- [ ] 本地演示与用户体验验收；D-012 验收通过后创建 PR。此会话不修改生产文章/观点/日报。
