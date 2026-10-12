# M3-A React 组件库原型

这版取代手写 HTML 控件和 SVG 图表作为当前评审入口。六页均用 React + TypeScript；Ant Design 负责通用基础组件，Recharts 负责图表。仍为独立示例数据原型，不连接生产 API，不完成 M3-A 正式开发。

验收记录（2026-10-12）：用户明确回复“验收通过”。验收版本包含左右并排的趋势图与期间合计、调用用途环形图、Ant Design/Recharts 基础交互、详情下钻和响应式主题。此记录仅确认原型，不替代正式后台接入真实 API 后的 D-012 页面验收，也不关闭 M2 或标记 M3-A 完成。

## 启动与检查

使用 Node.js 22.12 或更高的 22.x 版本；先执行 `corepack enable`。项目通过 `packageManager` 锁定 pnpm 12.3.4，CI 同样使用 Node 22 和冻结 lockfile 构建。

```bash
cd docs/design/m3a-admin-react
pnpm install --frozen-lockfile
pnpm dev
pnpm build
```

预览 `http://127.0.0.1:4187`；生产构建包括 TypeScript 检查。所有依赖精确锁定在 `package.json` 和 `pnpm-lock.yaml`，没有修改正式 `web/` 的依赖。

## 基础能力归属

| 能力 | 实际使用的组件 |
| --- | --- |
| 日期范围和快捷选项 | Ant Design `DatePicker.RangePicker`，包含确认、取消关闭、最大日期、中文日历 |
| 列表和分页 | Ant Design `Table` 与内置 Pagination，响应式列与局部滚动 |
| 搜索与筛选 | Ant Design `Input.Search`、`Select`、`Tabs`、`Segmented` |
| 详情与路径返回 | Ant Design `Drawer`、`Descriptions`、`Timeline` |
| 账目录入与校验 | Ant Design `Modal`、`Form`、`InputNumber`、`DatePicker` |
| 付款确认与反馈 | Ant Design `Popconfirm`、App context `message` |
| 提示、状态、说明 | Ant Design `Alert`、`Tag`、`Collapse`、`Empty`、`Progress` |
| 图表 | Recharts `ResponsiveContainer`、`BarChart`、`Bar`、`XAxis`、`YAxis`、`CartesianGrid`、`Tooltip` |
| 主题 | Ant Design `ConfigProvider` 与暗色算法，映射现有暖纸张/冷灰主题 tokens |

自定义代码只负责业务布局、北京时间口径、费用分摊、示例数据、URL 状态及跨页面筛选联动，不重写日历、表单验证、分页、弹窗焦点或图表坐标。

## 体验路径

1. 打开顶部日期范围，选本月与最近 24 小时。两者保留各自自然日/滚动时刻口径；自定义日期需要确认，关闭未确认日历不改变查询。
2. 点击总览来源卡片，切来源排序，进入来源详情和该源文章；详情抽屉内可继续查看所属事件并返回原详情。
3. 回总览点文章指标，不应残留刚才的来源筛选。
4. 总览的文章与调用费用趋势左右并排，各自左上显示所选期间合计；手机纵向排列。点击任一图的柱子进入对应时段明细，保留全局日期；返回上一页恢复总览。
5. 费用固定账目新增费用，空名称/非正金额由 Form 校验；确认付款使用 Popconfirm，仅修改演示数据。
6. 六页手机 400px 下可读，表格局部滚动。手机日历保留库的完整双月和快捷范围，弹层内部可横向滚动，不让整个页面溢出。
7. 桌面切换深浅色；刷新可恢复 URL 查询，模拟账目刷新后重置。

费用构成增加调用用途环形图，合计与右侧用途表一致，显示占比并支持点击进入该用途调用。此图明确不含固定费用；固定费用继续通过独立账目与分摊汇总查询。无费用时显示空状态，不能生成假占比。小额费用纵轴使用足够精度，避免多个刻度显示为同一金额。

## 正式实施边界

正式后台复用此组件选型，仍按 M3-A 分 PR 交付。通过懒加载后台路由与图表，让阅读页面不用加载后台组件库；原型当前单入口构建，不用其包大小作为正式交付基线。TanStack Query 与现有路由继续复用，后台查询不能加入日报离线持久化。

来源数据与新闻均为示例，8 个源不代表生产源数。费用包含示例人工汇率，缺失历史字段仍显示未记录。任务重跑、配置写入、聚类纠正随 M3-C 实施。

固定费用按与查询相交的北京时间自然日分摊，今日按一个覆盖日计；滚动 24 小时可能与两个自然日相交，不代表按小时分摊。调用费用仍按精确时刻统计。演示付款仅有日期，为便于筛选暂取当日 12:00；这不是已确认的付款时刻，正式 A4/A5 必须区分真实付款时间与仅有日期的记录，不继承该近似。原型只呈现部分筛选控件，正式版语言、地区、类型、处理与质量状态按产品设计实现。

参考：[Ant Design RangePicker](https://ant.design/components/date-picker/)、[主题配置](https://ant.design/docs/react/customize-theme/)、[Recharts BarChart](https://recharts.github.io/en-US/api/BarChart/)。
