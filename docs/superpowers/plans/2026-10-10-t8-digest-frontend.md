# T8 前端路由与日报实施计划

**Goal:** 三页导航与可切换历史日期的日报页面，按 T-D1 设计交付本地体验。

**Architecture:** React Router 管路由，TanStack Query 按日期缓存日报，复用事件数据模型与安全外链。页面拆成 App、FeedPage、DigestPage、DigestItem，报告复用 ReportPanel。

**Tech Stack:** React、TypeScript、Tailwind、React Router、TanStack Query、Vitest。

- [x] 补路由与日报测试并确认失败；新增 react-router-dom 依赖。
- [x] 分离 FeedPage，App 实现桌面侧栏和手机底部导航，main 注册 BrowserRouter。
- [x] api.ts 接入日报与 404 区分；DigestPage 实现北京时间日期导航及错误/空状态。
- [x] DigestItem 实现热度排名、摘要和溯源摘录；复用 safeHref。
- [x] 运行 lint/typecheck/test/build 及后端回归；独立代码评审。前端 26 项、后端 109 项通过；跨北京时间午夜与恢复前台的日期更新已补测试。
- [x] 启动独立演示数据库、API 与 Vite：页面 `http://127.0.0.1:5173/digest`；演示日期 2026-10-08 至 2026-10-10，10 个事件。演示数据库 `unspun_t8_preview` 与原本本地库隔离，不调用真实 LLM，不改生产数据。
- [x] 交用户实际体验桌面/手机/主题/历史路由。浏览器自动检查工具不可用；用户于 2026-10-10 回复“没问题，验收通过”，验收依据为用户体验。
- [x] 向用户交付体验地址和验收步骤，并获得明确验收通过；D-012 前置条件满足，进入提交 PR 流程。
