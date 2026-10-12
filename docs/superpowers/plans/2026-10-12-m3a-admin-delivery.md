# M3-A 后台查询版交付拆分

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement each approved subproject task-by-task. 本文是 PR 级交付拆分；每个子项目开工前单独写代码级实施计划，不将全部后台作为一个执行任务。

**Goal:** 交付默认总览、历史查询、全部运行成本和六页查询工作区，以可交互原型先验证布局与查询路径。

**Architecture:** React 后台独立路由，FastAPI 分领域查询，复用 Postgres 历史数据；新增周期费用和审计数据通过增量迁移实现。M3-A 不执行管线任务或配置 PR，缺失历史字段明确未记录。

**Tech Stack:** React、TypeScript、Ant Design（日期/表格/表单/弹窗）、Recharts（图表）、TanStack Query、FastAPI、SQLAlchemy、Alembic、Postgres。当前评审原型为 `docs/design/m3a-admin-react/` 的独立 Vite 项目，原静态 HTML 留档；正式后台依赖在 A1 引入并按路由懒加载。

---

## 当前交付与开工边界

- [x] 六页原型：`docs/design/m3a-admin/index.html`、`prototype.css`、`prototype.js`、`tokens.css`，第二版补 `refinement.css`、`range-picker.js` 与本地 flatpickr，只用明确标注的示例数据。
- [x] 浏览器检查：导航、自然日/滚动区间、自定义日期、图表/指标下钻、来源排序、文章/事件详情、费用口径、模拟账目表单及手机布局。第二版追加取消/应用/刷新、图表纵轴/精确读数/键盘、下钻返回与旧筛选清除；周期实际执行不在静态原型中实现。
- [ ] 提供本地预览地址与体验步骤，请用户验收原型；原型验收不等于生产页面验收。
- [ ] M2 收尾及正式 M3 任务板确认后，按下面独立子项目细化与实现。M3-A 查询展示不等待 D–F 的准入/进展数据。

## PR A1：查询时间契约与后台导航

**目标：** 独立后台工作区、可恢复筛选、自然日/滚动时间契约，旧 `/report` 可兼容进入。

**文件：** 新建 `server/src/unspun/api/admin/__init__.py`、`ranges.py`、`schemas.py`；修改 `server/src/unspun/api/app.py`、`web/src/App.tsx`；新建 `web/src/admin/AdminLayout.tsx`、`DateRange.tsx`、`adminApi.ts`、`adminFilters.ts`。

**组件选型：** 修改 `web/package.json` 和 lockfile，引入 Ant Design、Recharts 及其所需日期/图标依赖，复用已安装的 React，不另建基础控件。`ConfigProvider` 映射现有主题；`DateRange.tsx` 包装库的 `RangePicker`，只承担北京时间转换和业务范围。后台路由懒加载，阅读入口不加载后台库。以 React 原型完成库集成验证，不照搬静态 HTML 的日期实现。

**接口：** 统一接受带时区的 `start`/`end`、分页 `page`/`page_size` 和白名单排序；返回 `range`、`as_of`、`items`、`total` 与缺失信息。左闭右开，未来截止截到快照时间。页面默认今天/Asia/Shanghai，URL 保存筛选，返回列表保留状态。

**验证：** `server/tests/test_admin_ranges.py` 覆盖北京时间跨 UTC 日、周一、月/年边界、反向/无时区区间；`web/src/admin/adminFilters.test.ts` 验证刷新/下钻筛选保持；`AdminLayout.test.tsx` 验证六入口、旧路由与错误状态。执行后端 ruff/pyright/pytest 与前端 lint/typecheck/test/build。只读 API 不泄露配置密钥。

**依赖：** 已批准原型；不依赖费用迁移。各真实页面随下一子项目上线，未交付页明确说明能力，不能显示假统计。

## PR A2：来源、文章与事件历史查询

**目标：** 通过后台真实查源健康、抓取明细、入库文章、归属与评分；先建立总览下钻目标。

**文件：** 新建 `server/src/unspun/api/admin/sources.py`、`content.py`、`exports.py`；新建 `web/src/admin/SourcesPage.tsx`、`SourceDetail.tsx`、`ContentPage.tsx`、`ArticleDetail.tsx`、`EventDetail.tsx`；按真实查询计划决定必要的增量索引迁移。

**接口：** `/api/admin/sources`、`/sources/{id}`、`/articles`、`/articles/{id}`、`/events`、`/events/{id}`，包括区间、来源、关键词、语言、处理状态和白名单排序。文章默认 `fetched_at`，可切换 `published_at`；事件最早/最新报道时间取有效文章发布时间。列表只选必要列，详情再读取正文与证据，不批量加载每个事件全文。

**验证：** 数据库集成测试覆盖旧源移除仍可查询、成功零更新、最近错误取真实最新记录、空记录成功率未知、发布时间缺失、入库/报道筛选差异、搜索特殊字符、确定性分页、跨事件引用校验。导出复用筛选、防 CSV 公式注入。页面体验包含异常优先/产出排序切换、来源到文章再到事件。不提供重跑或聚类写入。

**依赖：** A1。

## PR A3：运行、配置与已有操作记录查询

**目标：** 查看现有轮次、积压与失败项，配置只读；无历史阶段耗时或审计明确显示未记录。

**文件：** 新建 `server/src/unspun/api/admin/runs.py`、`configuration.py`；新建 `web/src/admin/RunsPage.tsx`、`RunDetail.tsx`、`ConfigurationPage.tsx`。积压条件复用 `pipeline/summarize.py` 与 `pipeline/score.py`，不另写相互冲突的定义。

**接口：** `/api/admin/runs`、`/runs/{id}`、`/backlog`、`/configuration`。轮次按实际 `PipelineRun` 字段查询，不能从一个源失败推断整轮状态；结束/耗时没有记录时返回 null 和缺失说明。当前积压标为当前，不伪装历史快照。配置响应只返回批准字段，环境凭证只能返回配置状态。

**验证：** 集成测试比对现有 backlog 规则、历史缺字段、配置脱敏、异常/无数据区分；手机详情可读。M3-C 队列、按源调度、真实阶段遥测和配置变更后续接入，不在本 PR 新建假手动任务。

**依赖：** A1；对象详情可接 A2。

## PR A4：周期费用账目与成本计算

**目标：** 完整维护固定费用、付款、周期规则、汇率和审计；费用计算可供查询 API 复用。

**文件：** 增量迁移置于 `server/alembic/versions/`（编号以实施时 head 生成）；修改 `server/src/unspun/core/models.py`；新建 `server/src/unspun/core/expenses.py`、`expense_allocation.py`、`api/admin/expenses.py`；测试 `server/tests/test_expenses.py`、`test_expenses_api.py`。

**数据：** 周期规则及版本、账目（规则/覆盖区间唯一）、付款状态/日期、原币金额 Decimal、汇率及有效日期、账务审计。确认付款不是外部扣款。金额修正不覆盖历史版本。规则账目生成幂等，可在账目查询/确认入口按限定日期物化；M3-C 前不引入第二套永久任务调度。

**计算：** 固定费用按服务覆盖自然日分摊，已覆盖未确认费用单列预计；调用时间记期间成本，充值仅记实际支出。无汇率按原币分组并提示未换算。月末规则锚点不足日期使用该月最后一天，后续继续原锚点；年付闰日同理。币种代码/正金额/覆盖区间/付款日期均验证，变更并发用版本条件写入。

**验证：** 月末、闰年、跨年、覆盖边界、部分区间分摊总额一致、账目重复生成、停用/涨价保留历史、已付改动审计、预计转已确认不双计、充值不再次计成本、缺汇率不默认为 1。写 API 检查身份与请求来源，全部费用操作留审计。

**依赖：** A1；不依赖后台管线操作。

## PR A5：费用查询与账目页面

**目标：** 全部费用历史查询、口径切换、趋势和调用下钻、账务表单/付款确认/站内续费提醒。

**文件：** 新建 `server/src/unspun/api/admin/costs.py`；新建 `web/src/admin/CostsPage.tsx`、`CostBreakdown.tsx`、`ExpenseForm.tsx`、`ExpenseLedger.tsx`、`Renewals.tsx`；测试 `server/tests/test_admin_costs.py`、`web/src/admin/CostsPage.test.tsx`。

**接口：** `/api/admin/costs`、`/costs/calls`、`/expenses`、`/expense-rules`、`/exchange-rates`。调用汇总直接聚合现有 `LlmUsage`，未知历史关联对象明确未记录；不要求未来任务遥测才能展示历史成本。模型/用途筛选只影响调用子集，固定费用单列，区间总成本与筛选调用小计不得混用。

**验证：** 汇总与逐条金额一致、费用精度、期间成本/支出/预计拆分、模型预算独立原币计算、本月预算不被历史筛选伪装、自然日与最近 24h 差异；表单错误与重复提交、付款确认与续费列表；CSV 范围/小数/公式防护。页面离线不允许账务提交；后台查询不进入日报持久化缓存。

**依赖：** A4；下钻接 A2/A3。本 PR 不补造调用结果/文章关联，新遥测独立纳入 C 的实施设计。

## PR A6：总览整合与浏览器验收

**目标：** 默认首页组合真实当前状态、区间产出、全部成本、趋势、异常与最近运行，并保证所有下钻可用。

**文件：** 新建 `server/src/unspun/api/admin/overview.py`、`web/src/admin/OverviewPage.tsx`、`MetricCard.tsx`、`TrendChart.tsx`；修改 `web/src/App.tsx`；测试 `server/tests/test_admin_overview.py`、`web/src/admin/OverviewPage.test.tsx`。

**规则：** 查询 API 共享快照截止时间和聚合函数；当前状态单列，统计结果 null 不显示零。新事件标签为新建事件，按系统创建计数。图表使用 Recharts，颜色沿用 tokens。阶段实时状态缺失显示未记录，不因最近轮次存在而宣称正在健康运行。

**修订：** 图表统一采用 Recharts 的 `ResponsiveContainer / BarChart / XAxis / YAxis / CartesianGrid / Tooltip`，启用库的可访问层；不手写 SVG 坐标、刻度、Tooltip 或尺寸计算。业务组件只处理聚合后的数据与下钻目标。

**验证：** 指标与目标明细数量/费用一致，今天/昨天/自定义下钻保留范围，获取失败不清空为零，400px 无页面溢出，键盘/暗色可用；可访问表格摘要与图表数据。真实后端与前端检查后启动本地服务，用户验收通过再开页面 PR。M3-A 完成记录只覆盖实际数据与交付项。

**依赖：** A2、A3、A5。

## 原型体验步骤

1. 总览默认今天；打开范围选择器，用快捷范围或日历切昨天、本月、自定义。取消不触发查询；应用后统计与图表变化，当前状态不随日期改变。
2. 点击新入库文章或费用，检查区间跟随进入目标页且清除无关的来源/模型筛选。图表显示纵轴、单位和精确读数；时段下钻不改全局范围，可返回总览恢复原上下文。
3. 费用切期间成本/实际支出，查看调用用途过滤、账目、续费和模拟新增费用。
4. 信息源切异常优先/产出，筛选后打开详情，再查文章/事件。
5. 运行详情中的历史耗时及配置审计缺失不显示假值；管线操作仅说明 M3-C 排期。
6. 手机宽度、暗色与键盘导航；所有示例明确标注，无生产操作。

## 2026-10-12 第二版体验修订

用户反馈第一版日期控件分散、入口太小、图表缺纵轴、内容与联动混乱。新版原型将总览收敛为三项核心指标、单图切换、整块状态入口与少量异常；费用取消重复统计卡片，来源摘要收成一行，口径说明渐进展开。A1 需落实成熟范围组件、日期草稿/取消/应用、全局与局部范围、按页筛选和浏览器返回；A6 需落实零起点纵轴、单位、悬停及键盘读数、手机可读刻度，并用真实路径验证指标与明细一致。新增组件选型须在子项目设计中决定，静态原型 vendor 不自动引入生产包。

## 2026-10-12 React 与组件库修订

用户指出基础组件和绘图无需手写，要求复用开源库。当前原型迁移到独立 React + TypeScript 项目，实际使用 Ant Design 与 Recharts，不再用原日历外围、手写分页/表单或 SVG 图表作为实现依据。配置与主题遵循现有栈；正式后台采用同一选型，库版本在 A1 按主应用 React 兼容性锁定。时间口径、费用账目、查询和下钻仍属于业务代码，不能用组件库替代这些规则。
