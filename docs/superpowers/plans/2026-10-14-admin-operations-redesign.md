# 运营工作台实施计划

**目标：** 将正式后台重组为异常优先、数据驱动的运营工作台。
**架构：** 保持 React Query / FastAPI 查询契约，布局、图表、筛选与业务页按责任拆分。使用现有 Ant Design 基础控件和 Recharts，自定义后台视觉。

- [x] 重做 AdminLayout.tsx 导航、搜索、时间与刷新；新增 WorkspaceSearch.tsx。
- [x] 重做 OverviewPage.tsx 优先级；新增 OverviewOperations.tsx 组织健康与积压，修改 TrendChart.tsx 支持面积图与折叠数据表。
- [x] 新增 FilterContext.tsx 和 SelectionExport.tsx；调整 SourcesPage.tsx / ContentPage.tsx 高频筛选、更多筛选与列表编码。
- [x] 修改 RunsPage.tsx 阶段导航、CostsPage.tsx 预算展示、CostBreakdown.tsx 图表构成、ConfigurationPage.tsx 信息分组。
- [x] 重写 admin.css 的后台视觉系统与响应式样式，保持阅读页隔离。
- [x] 构建、lint 与页面浏览验证；启动真实本地 API、提供预览 URL 和设计文档。

详情补充：ArticleDetail 折叠正文并转换状态文案；EventDetail 使用 ScoreBreakdown 展示客观与重要性维度。更新已有测试的导航文案和接口隔离夹具；后台 24 项已有测试通过。用户已在第二轮调整后明确回复“通过”（2026-10-14），页面体验验收完成。
