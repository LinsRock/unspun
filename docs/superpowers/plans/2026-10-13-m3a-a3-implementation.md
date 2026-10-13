# M3-A3 运行与配置查询实施计划

**目标：** 在已交付的后台框架中查询真实 AI 轮次、当前积压、只读配置与现有操作记录情况。

**依据：** `docs/tasks/m3.md` A3、`docs/superpowers/plans/2026-10-12-m3a-admin-delivery.md` PR A3、后台设计的“运行与任务”“配置与操作记录”。

**边界：** `PipelineRun` 仅有记录时间和处理计数。结束时间、各阶段结果、运行状态、关联费用和历史审计均返回缺失语义；不能由计数推断成功。当前积压复用 `pending_summary_conditions`、`abandoned_summary_conditions`、`pending_embedding_conditions` 和 `pending_score_conditions`。手动任务留在 M3-C。

## 任务 1：只读运行 API

- [x] 先写 API 测试：半开时间区间、稳定分页、详情 404、记录缺失字段、单个源失败不改变 AI 轮次状态。
- [x] 确认测试因接口不存在失败。
- [x] 实现 `/api/admin/runs` 与 `/api/admin/runs/{id}`，仅返回数据库真实字段及缺失说明。
- [x] 运行定向测试。

## 任务 2：当前积压 API

- [x] 先写 API 测试：待摘要、摘要重试耗尽、待 embedding、待评分；详情分页；当前积压不受历史范围影响。
- [x] 确认测试失败，随后实现 `/api/admin/backlog`，所有条件调用现有管线谓词。
- [x] 运行定向测试。

## 任务 3：配置 API

- [x] 先写 API 测试：来源和管线批准字段、预算与凭证配置状态、响应不含密钥/数据库 URL；历史审计明确未记录。
- [x] 确认测试失败，随后实现 `/api/admin/configuration` 的显式响应模型和字段白名单。
- [x] 运行定向测试、ruff、pyright。

## 任务 4：正式后台页面

- [x] 先写前端交互测试：运行空态与失败态、分页与详情、当前积压、配置脱敏状态、未记录审计、窄屏可读。
- [x] 确认测试失败，随后使用 Ant Design 表格、抽屉与标签页实现运行页和配置页，并接入现有 URL 范围。
- [x] 运行前端 lint、typecheck、test、build；运行后端全套检查。
- [x] 启动本地预览并做 400px 宽浏览器检查。
- [x] 提供地址和体验步骤；用户依 D-012 体验并于 2026-10-13 明确验收通过。
