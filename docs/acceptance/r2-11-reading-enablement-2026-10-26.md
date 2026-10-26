# R2-11 首批阅读入口启用准备

**出口：待明确启用授权的 PR；未合并、未部署，生产首页与开关不变。** 本批只准备既有合格内容的混合读取和发现首页，不代表完整话题链、真实模型质量或整个 R2 通过。范围见[本批契约](../superpowers/specs/2026-10-26-r2-11-reading-enablement.md)；页面沿用 [R2-10 已通过的体验](r2-10-reading-preview-2026-10-26.md)，这里只补正式配置及旧链接兼容，不补记新用户评分。

基线 `origin/main d975e9d`；独立 worktree `/Users/li.cong/.config/superpowers/worktrees/unspun/r2-reading-enablement`，分支 `feat/r2-reading-enablement`，`server/.venv` 和源码导入指向本 worktree。新测试库 `unspun_r211_test_20261026`、真实阅读库 `unspun_r211_reading_20261026` 均从空库迁移至 `000021`；本 PR 无迁移。

## 只读生产与账本截面

2026-10-26 **15:52–16:11（北京时间）**，数据库使用 `REPEATABLE READ` + `READ ONLY`，只读取现有账本，不初始化预算、不查询提供方、不结算费用。以下是有时限的观察，不是新可用预算。

| 项目 | 已核对结果 |
| --- | --- |
| 实际部署 | API、受控 R1 worker、web 均为 `51fc29e0a87b1768537fe62ae00b2c0c3e03fec0` 固定镜像；schema `000021`，114 个服务端源码哈希与基线相符；正式首页 `events`、`engineering_preview: false` |
| 关闭范围 | 成员处理、合成、话题发布、混合、话题偏好全为 false；话题、成员、合成、偏好为 0；未登录正式读取 401，认证后的关闭入口 404。生产 `.env` 尚无两个 R2-11 覆盖键 |
| 合格内容 | 初始 373 条、8 路既有来源；收尾 374 条，原 373 条 ID/材料/卡片版本/正文逐项保持，旧 R1 自然新增 `9909`。没有导入或发布工程话题 |
| 读者与历史 | Reader v14 / recommended，无当前兴趣或内容反馈，保留 14 条变更；旧事件偏好 v15 / newest / today。读者、旧事件、观点、6 份日报、预算行均保持；材料/身份/URL 原行保留 |
| 生产预算 | 原 `$15` 总额、生产 `$13.50`、评测 `$1.50`、审核 `$0.40/24h` 不变。生产 stage caps 仍为 card 10 / guide 2 / embedding 1 / legacy 13.50，没有新话题分配 |
| 生产账本 | 收尾已知费用约 `$8.09014430`，历史 carry `$1.58359581`，未知预留 **32 笔 / `$1.065444`**，占用约 `$10.73918411`。原 **29 笔 / `$0.979535`** 的行哈希全部保持；不把预留当实际费用或可释放余额 |
| 原评测 | 8 笔未知 / `$0.514613` 原行保持；累计已知约 `$0.44635293`、占用约 `$0.96096593`，原阶段分配和 `$0.30` 累计池/paid-stop 保持 |
| 缺失证据 | 当前提供方余额未查；生产最后已存提供方观察仍是 10 月 18 日，原评测没有当前提供方读数。用户主观质量、遗漏参考、R2-07 真实话题质量、完整新内容任务链均未验 |
| 保留资源 | 432 份既有验收/评测/配置文件字节一致；R2-04 的 331 份原件、3 个观察容器和原 worktree 保留；R2-10 预览库行/费用及两个持续服务保持；生产 R1 worker 1、legacy worker 0，仅发布 `127.0.0.1:8080` |

**本批主动生成、embedding、付费重试、模型提供方查询均为 0。线上整个窗口并非零调用：** 既有 R1 在 16:00 自然追加 5 笔 card 物理请求，其中 2 笔已有费用共 `$0.0010344`、3 笔新增未知 hold 共 `$0.085909`。这些由原消费者继续运行产生，单列保留，未代查或结算。派生表从 1,301 行变为 1,307 行，原行中 1,272 条整行哈希一致；不声称派生全表静止，也不把自然新增算成本批话题链验收。

## 精确开关与入口

| 控制 | 基础/本地默认 | PR 的生产默认 | 回退含义 |
| --- | --- | --- | --- |
| `R2_HYBRID_ENABLED` → API `UNSPUN_R2_HYBRID_ENABLED` | false | true | false 使 mixed API 返回 404，首页也回 events |
| `R2_DISCOVER_HOME_ENABLED` → API `UNSPUN_R2_DISCOVER_HOME_ENABLED` | false | true | false 只将 `/` 恢复旧事件流，mixed 可独立保留 |
| `UNSPUN_R2_MEMBER_PROCESSING_ENABLED`、`UNSPUN_R2_SYNTHESIS_ENABLED`、`UNSPUN_R2_TOPIC_PUBLICATION_ENABLED`、`UNSPUN_R2_TOPIC_PREFERENCES_ENABLED` | false | API/worker 显式 false | 本批无开启路径 |
| worker 的 mixed/home；`admin_local_preview` / `r1_local_preview` | false | false | 读取能力不接到消费者，不使用预览身份 |

应用本身的首页开关仍默认 false；正式 `/api/reading-capabilities` 只有 mixed 与 home 同时 true 才返回 `home: discover`，`engineering_preview` 固定 false。PR 合并部署会采用生产开启默认值，**因此不能把合并当作无行为变化的交付**；`.env` 显式 false 优先于默认值。没有修改模型、来源、排序参数、账务或付费阶段分配。

复用 `unspun.api.app:app`、正式 Access JWT 与原公开资格。普通 `/` 转 `/discover`；旧 `/?sort=…`、`/?range=…`、`/?unread_only=…` 连同其他参数/hash 继续进入事件页。`/events`、`/digest?date=…`、`/reading`、`/reading/:id` 及 PWA `/digest` 均保持。页面主体/视觉、独立详情资格和旧排序未改。

## 隔离验证与负载

新阅读库逐行复制初始 373 条真实合格 Article、384 份材料、1,153 条派生、来源观察/身份/URL 及必要读者状态，没有话题、worker、模型密钥或 BudgetPolicy。正式应用运行于 `127.0.0.1:8011`、网页 `:5179`；认证只将 JWKS 获取替换为本地公钥传输，仍由原认证函数验证真实签名、issuer、audience 和有效期，未覆盖认证依赖、未运行 evaluation 工厂或放宽资格。

- 真实 API 推荐/最新各遍历 12 页（每页 20 条），同为 240 个唯一内容；无话题、重要性和公共关注信号均为空。浏览器按页面原有每页 10 条验证两页返回及滚动位置、内容正/负反馈/撤销、来源关注/取消、手机/桌面明暗主题及离线禁写，无页面脚本错误。
- 实际重启隔离 API 后，Reader 状态、排序和未过期游标结果保持；依次验证 home=false、mixed=false/home=true、两者 false，再恢复。旧链接可读，关闭 mixed 的直接发现页明确报错，不继续显示旧列表。隔离 Reader 审计从 v14 正常增至 v23，最后偏好恢复为空、排序 recommended；生产 Reader 未写入。
- 读取前后原材料/派生/身份/历史偏好字节保持；任务、物理调用、预算、话题均为 0。另用 pending / retry_wait / budget_deferred 的既有导读任务工程样本核对：读详情返回原任务状态，完整行不变，不创建、认领或重放任务。没有点击按需生成导读或后台付费入口。
- 当前配置 `signals: []`、无兴趣时，只读 lane 上限 240；兴趣 lane 至多 120，全部内容 lane 理论上限 600（话题始终 0），最多 256 个兴趣资源。两种排序共享候选；初始另 133 条合格详情不在这次候选内，抽查 `8861` 按 ID 仍可读，边界外效果保持 `not_evaluated`。
- 每次 mixed 分页都会重算有界池并核对快照，不预加载全部历史，不写快照表。实际读取 **7 条 SQL**；本机 HTTP 推荐约 **0.46–0.56s**、最新约 **0.40–0.46s**。生产在开关仍 false 时，仅一次只读调用相同候选函数：召回 **3.2454s**、推荐排序 **0.5378s**、最新排序 **0.0072s**，240 候选/7 SQL，设置单 SQL 5s 超时；这不是已启用 API 的端到端 SLA。现有 10,000 条历史压力样本仍 7 SQL、快照不变，632 候选工程上限排序约 0.23s。

检查：后端全回归 **1,333**、保留旧付费任务的最终定向 **5**、前端 **142** 项通过；Ruff/格式、Pyright、oxlint、TypeScript、正式 build 通过；部署 **19**、CI 路由 **11** 项通过；固定旧排序 **40** 例与基线结果逐字节一致；PWA 安装、IndexedDB 恢复、离线新标签/刷新、日期导航和 API 缓存排除通过。差异审查覆盖正式认证、开关调用方、旧 URL/排序、Reader 原接口、资格与候选界限、消费者和预算初始化路径。

一次性脚本/结果仅留 `/Users/li.cong/.cache/unspun/r2-11-enablement/`，不提交整库导出、令牌、截图或运行日志。持续 R2-10 预览按原交接恢复；本批新 worktree/venv/隔离库保留供审查。

## 获授权后的部署核验

以下步骤**本批未执行**；必须先取得“仅既有合格内容 mixed + 发现首页”的明确启用授权。

1. 刷新 `origin/main` 和当前生产版本/读者/合格集合/未知预留，只读列出与本截面的差异。确认预算仍是已有有效 cutover、paid-stop 与四个关闭 gate 保持；若策略缺失/无效，停止，不通过初始化、提供方查询、结算或补生成修复。
2. 必需 CI 全绿、复核 `.env` 两个覆盖键后再合并。正常 CI 用目标固定镜像迁移并部署；本批 schema 不变。旧 `initialize-production` 只允许复用既有已启用策略的分支（已核对 worker 预检通过），不得走首次提供方 cutover。记录实际 API/worker/web 镜像及 `APP_VERSION`，不能只看主干 SHA。
3. `/api/health` 应为目标 assembled version、database ok；schema 仍 `000021`，仅 loopback 8080，R1 worker 1 / legacy 0。用正式 Access 登录核验 `hybrid:true, topic_preferences:false, home:discover, engineering_preview:false`；未登录仍 401，话题偏好及工程话题 ID 仍 404。API/worker 的四个关闭开关逐项核对。
4. 普通 `/` 打开发现，旧带筛选参数的根链接、事件、日报日期链接和独立详情仍可读。推荐/最新只出现现有合格内容，材料/版本不降级；不导入工程话题。对账原历史读者、账本/预留及新自然 R1 差异，不能用总量变化推断本批发生付费。

## 配置回退

优先回退配置，**不恢复数据库备份、不降级 schema、不重置 Reader/预算或删除任务**。在主机 `~/unspun/.env` 将下列键分别设为唯一的 false 值（替换已有键，不输出整个文件）：

```dotenv
R2_HYBRID_ENABLED=false
R2_DISCOVER_HOME_ENABLED=false
```

在当前 `~/unspun/deploy` 目录，使用正在运行的固定镜像和版本，只重建 API，不调用预算初始化或重启消费者：

```bash
r211_api_image=$(docker inspect -f '{{.Config.Image}}' unspun-api-1)
r211_web_image=$(docker inspect -f '{{.Config.Image}}' unspun-web-1)
r211_version=$(docker exec unspun-api-1 python -c 'from unspun.core.config import get_settings; print(get_settings().app_version)')
SERVER_IMAGE="$r211_api_image" WEB_IMAGE="$r211_web_image" APP_VERSION="$r211_version" \
  R2_HYBRID_ENABLED=false R2_DISCOVER_HOME_ENABLED=false \
  docker compose --env-file "$HOME/unspun/.env" -f compose.yml -f compose.prod.yml \
  up -d --no-deps --pull never --no-build --force-recreate api
```

随后新会话/强制刷新验证 capabilities 回 `events`、mixed 404、旧主页/详情/偏好正常，Reader/账本/预留不变；已打开页面需重新拉取能力，不声称即时推送失效。只退首页时仅将 home 设 false 并用相同方式重建 API，mixed 可保留。若必须退镜像，已核对的兼容固定版本是上述 `51fc29e`（server/web），仍保留当前退役后的部署文件、两键 false 及 `000021`；不得恢复包含 legacy worker 的旧 Compose。

## 有界观察与未完成项

授权部署后只对单读者观察，首轮、约 30 分钟、24 小时各检查推荐/最新的首页和一页续页，**最多 12 次 mixed 探测、并发 1**，不建持续轮询/压测或付费任务。首轮可做一次 API 进程重启后复读，计入探测上限；已过期/发生自然依赖变化的游标应明示重载，不能拼接旧快照。记录延迟、SQL/候选界限、401/404/409/5xx、DB/容器资源，以及只读任务/账本增量；自然 R1 请求单列。

资格泄漏、读请求写任务/账务、关闭 gate 异常、旧链接或历史数据受损立即回退；单读者连续两次超过 5s 或一次超过 10s、持续 5xx/资源异常也先关闭首页和 mixed，再排查。当前生产查询样本接近 4s，**负载风险仍需真实端到端观察**，不据一次诊断宣称性能验收完成。没有取得启用后观察或新用户主观评价，不勾选 R2-11 整体清单。

R2-06 继续暂缓，R2-07 真实质量待验，R2-04 原结论保持；清理与 R3 未开展。
