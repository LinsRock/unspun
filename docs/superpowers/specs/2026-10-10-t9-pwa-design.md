# T9 PWA 与离线日报设计

沿用已确认的 M2 T9 与 T-D1 规范：vite-plugin-pwa / Workbox 生成 service worker 和 manifest，TanStack Query 通过 IndexedDB persister 保存日报快照。应用外壳预缓存，离线导航回退到 index.html；API 与 Cloudflare Access 路径不参与导航回退或运行时缓存。

安装名称 Unspun，启动路径 /digest，standalone 模式；图标使用现有蓝色强调色与暖纸张背景，并提供 192/512 PNG、maskable 与 Apple touch 图标。开发服务器不启用 service worker，验收使用生产构建预览。

PersistQueryClientProvider 在查询开始前恢复缓存，只持久化非空日报数据（包含刷新失败后仍保留的快照），保留七天，gcTime 与 maxAge 一致。缓存版本按数据结构升级，普通部署不清空日报。存储不可用时保持在线可用，日志报告存储失败。最新一期同时保存 report_date 对应的缓存，使安装后的默认日期页能复用快照。

离线且有数据时继续显示快照；离线且没有数据时提示先联网加载对应日报，不显示永久加载状态或假装生成了日报。重新联网由 Query 恢复查询；有快照时刷新失败保留正文。

验收：单元测试使用真实 fake-indexeddb 存储并重建 QueryClient；生产构建浏览器测试在线加载、service worker 就绪、离线刷新 /digest 与历史导航；检查 manifest、图标尺寸、Caddy 的资源供给与 no-cache 头。手机桌面安装和 Cloudflare Access 环境的飞行模式验收由用户完成（D-012），通过前不创建 PR、不勾选 T9。
