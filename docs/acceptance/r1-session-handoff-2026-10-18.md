# R1 会话交接 · 2026-10-18

用户最新要求：本 session 收尾，给出可在新 session 继续执行的 prompt。**不在本次交接中启用生产**。R1 尚未具备最终用户验收条件，不能结案或进入 R2/R3。

## 当前交付与分支

- 已合并且实际部署：#91 阅读分页返回修复；#83 card v9/guide v5 最终质量；#92 真实任务关联单位成本；#93 正常部署中的生产预算初始化/预检。启用前运行版本为 `6cf450bd6527cb354003cc6beab5354d94291ea3`，这是组装版本，API 固定镜像 `f095e15`、web 固定镜像 `e403d97`；schema `000015`。
- 本交接 PR [#95](https://github.com/LinsRock/unspun/pull/95)只同步文档/事实和修复一个过期日期测试，不改变运行配置。`docs/tasks/r1.md` 更新为 16/19 项技术交付完成，15–17 保留未完成。13/14 的技术收尾复用既有真实页面/API/回归，明确省略重复手机/撤销点击；这不等于用户最终体验通过。
- **启用草稿 PR [#94](https://github.com/LinsRock/unspun/pull/94)**：分支 `feat/r1-production-rollout`，worktree `/Users/li.cong/.config/superpowers/worktrees/unspun/r1-production-rollout`，准备提交 `edf09b3`。生产配置尚未合并。该分支有 9 路来源阶段、R1 单副本及对应安全测试更新；下一 session 先同步 main，再继续此分支，不另起平行实现。
- docs 收尾 worktree `/Users/li.cong/.config/superpowers/worktrees/unspun/r1-session-close-20261018`。它只承载本交接与事实对账，不应拿其无启用的配置直接启动消费者。

## 下一 session 直接执行的剩余闭环

1. 读 `CLAUDE.md`、D-025/D-026/D-027/D-028、`docs/tasks/r1.md`、本文和 #94；fetch 最新 main，核对本地/远端分支与 CI。若本交接已合并，将 main 合入启用分支，保留已发布历史。
2. 核对 G3 的已有证据与明确限制：[阅读/反馈收尾](r1-final-reading-2026-10-18.md)、[真实 API 版本/撤销](r1-reader-final-api-2026-10-17.md)、[分页返回修复](r1-reader-return-2026-10-17.md)。用户已要求提速，可省略重复环节；不要冒充新增手机长文、撤销 UI 或外站播放检查。若浏览器恢复，可补最后真实页面体验；无可用窗口时继续独立的启用检查。
3. 复核 #94 的精确名单、材料范围、owner、Compose 和当前费用投影，取得**新的只读提供方读数**及生产实际状态。已有 provider 截面不当当前余额；预算初始化仍通过正常部署 hook，禁止直接 SQL/修改容器或创建平行额度。
4. 在 G1/G2/G3 与当前剩余预算满足后，按 D-025/D-026 自行审查、处理选中 CI、将 #94 设为 ready 并合并。旧 worker 必须始终零副本。只启用受控 R1。
5. 追加真实生产事实：版本/镜像/config 指纹、source owner/next_due、独立 discover/material/card/guide 任务与尝试、真实新内容及发布范围、失败/延期和每笔物理费用。核对后台 `/admin/content`、`/admin/costs` 的新条目/失败/未知费用下钻和单位成本，完成 15。
6. 按仓库正常发布/受控运行约定做实际重启恢复，核对既有任务/物理请求不重复、未完成任务可恢复、随后真实新条目可继续消费；保留前后 ID/费用。不能仅凭 API 健康、worker 在跑或配置合并勾 16。若某一路失败，关闭该路径并继续其他独立路径。
7. 最终对账 17：提供正式阅读、关注和后台入口，三类合格内容、反馈/撤销、任务/费用/来源与测试证据，列明真实剩余缺口，让用户进行 R1 最终验收。用户未接受前保留最后验收 checkbox；R2/R3 不启动。

## 生产启用范围与新发现

详见[首批记录](r1-production-rollout-2026-10-18.md)、[事先登记 v2](../evaluations/r1/production-rollout-v2.json)、[完整窗口](https://github.com/LinsRock/unspun/blob/eb5b19f749c8316174e9cc5f6e838d7bbb0aec85/docs/acceptance/r1-production-rollout/source-window.json)、[成本投影](r1-production-rollout/cost-projection.json)。不是重做规划。

完整 v3 窗口从 `2026-10-17T06:02:40Z` 到 `18:32:40Z`，跨上海 10/17、10/18。容器正常退出 0；两路各 26/26，52 条物理观察、104 份材料样本全部归档。

- BBC World：27 个不同材料 URL、10 个新身份，文章/视频分别核对，有界 G2 通过。本次独立登记 R1-16B **仅付费/发布 `media_description`**；普通文章仍不能付费/发布。
- **新华社继续关闭**：45 个不同材料 URL、109 个新身份，但 `2994b6e338ee4fe1a16ea5747ba4277f` 仅有 41 字策划/主编/记者/摄制/出品名单仍被标成视频简介；关键错误不以 51/52 比例抵消，不重写旧失败。该材料抽取器缺口尚未修复，若之后修复/扩大启用，须另补 G2，不能借此次交接补勾。
- 其余 8 路：BBC 中文、NYT World、WSJ World、早报中国/国际、豆瓣书评、人民日报头版、知乎日报，保留既有通过范围；8 路每 2 小时最多首条，BBC World 每 12 小时最多 30 条。共 9 路、原始候选槽上限 156/日、首轮最多 38。它是有限切片，不是全站覆盖。S 项与其他路径保持关闭。

投影按当前 card v9 已知每 ready 成本保守套到每个原始槽（包括无付费资格 BBC 文章），加 20% 重试/格式失败、每月 120 次显式导读及 $0.738 未来未知失败压力，剩余 14 天含首轮约 `$4.005564448`，当时保守生产 headroom `$4.30817409`。**余量较小，合并前必须刷新账户读数和本月余下天数**。它是场景，不是未知费用结算或保证上界，硬预算继续先行拒绝/延期。

## 测试与真实质量（不重做已完成付费评测）

- 当前契约：card `r1-card-v9`、guide `r1-guide-v5`、review v2。原模型不变：`google/gemini-2.5-flash-lite` 生成，`google/gemini-2.5-flash` 审核。
- 最终质量已在 #83 完成：card 原回归 18/18、T 5/6、后增 U 10/12；guide 回归 8/8、新材料支持者 7/8。格式/标签/网络失败全部保留并不发布，不为过关再调留出材料。
- [最终质量](r1-final-content-quality-2026-10-17.md)和[真实运行单位成本](r1-runtime-accounting-2026-10-17.md)区分 known 下界、未知预留、候选与 ready 分母；用户值得看/召回仍无标签，不虚构。
- #94 最终本地检查：**873 passed、0 skipped**，新建且已迁移的 `unspun_r1_rollout_tests_20261018_025805_b6e5`；Ruff/159 文件格式通过、严格 Pyright 0 错误 0 警告、Compose 旧 0/R1 1/唯一端口 `127.0.0.1:8080`。详见[test-evidence.json](https://github.com/LinsRock/unspun/blob/eb5b19f749c8316174e9cc5f6e838d7bbb0aec85/docs/acceptance/r1-production-rollout/test-evidence.json)。
- 初始两条旧测试要求所有来源全关，已改为精确登记名单与未合格路径关闭的围栏；跨日后另发现费用测试的固定结束日期已过期，改用当前测试时间窗口。初始 Pyright 缺 worktree `.venv`，建立共享链接后最终通过。不要把最初失败输出当最终结果。
- 不对原评测库或生产库运行 pytest。后续若改数据库逻辑，仍新建并迁移隔离库；只有 doc/配置追加时按影响范围检查，不重复全量无关检查。

## 费用与约束

原评测库仍为 `unspun_quality_r1_20261016`，同一账本/原模型，最后已知 **401** 物理请求、**394** 已知费用 **$0.3690100**、**7** 未知预留 **$0.484867**；同一累计评测分配 $1.50 可用 **$0.646123**。本轮启用准备/归档无新增付费。

项目 $15/月，生产 $13.50、评测累计 $1.50；生产 card $10、guide $2 及审核 $0.40/24h 硬限保留，评测显式审核上限 $1/24h。D-027/D-028 已有用户提额授权，不再询问，不把 provider limit 当新增余额。

最后提供方读数 `2026-10-17T17:03:45Z`：limit $15/月、usage/usage_monthly $9.19182591、remaining $5.80817409。生产原库在启用前没有 budget_policy/carry、R1 task/BR 仍 0；已有本月 legacy known 约 $7.6082301，部署 initializer 会用新 provider 读数建立差额 carry，不能抹掉历史或直接照搬评测策略。

原五笔未知只有两笔凭唯一 generation 记录结算，三笔仍未知；新增四笔也未知。`10/17 上海 16:17:31` 是本地请求起始，不是提供方已受理的证明，用户未找到对应日志不得补造。唯一带 header 的拒绝 `gen-1792228899-g8CyAm1fHk5FLCwMg6dG` 已两次只读查询为 404，未结算成零。不做无证据轮询或扩大付费重试。细节留[核对报告](r1-billing-reconciliation-2026-10-17.md)及最终质量附件。

43 条原用户评分继续为空；技术试验兴趣/反馈已在隔离阅读库按正常 API 撤销，最终 reader version 8、sort latest、无兴趣/反馈。另一端的最新排序保留，不能覆盖它来清理测试。

## 本机入口与私有原始证据

- 阅读 `http://127.0.0.1:5179/reading`，关注 `/interests`，代理真实 API `8113`，原评测库，22 条合格内容，明确 unpublished preview；不要将它当正式生产。web 在 `r1-reading-return/web`，API 配置为 `~/.cache/unspun-r1-content/quality-preview-config`。
- 只读成本预览 API `8114`，版本 `r1-runtime-cost-final-local-preview`；`/api/admin/costs` 展示 U11 实际 guide task 1、两次调用 $0.0021675。主 8113 仍是最终质量预览，切勿误停用户正在看的入口。
- `~/.cache/unspun-r1-content/ui-final/`：`guide-ready.png`、`preview-detail.png`、`video-detail.png`、`reading-return-proof.png` 为实际证据；后者才是修正后通过的返回图。中间失败图不替代最终结果。`api-final-read-and-undo.json` 明确最后撤销走 API。
- 浏览器工具：点击原始 MP4 触发 URL 限制后停止该 URL 操作；后续 Chrome 报无窗口、创建浏览器超时，未改用其他 UI 技术绕过。已向用户发可选恢复问题，尚无明确回复。新 session 可以重新按工具规则检查已允许的本地页面；不要访问被禁止 URL 绕过限制。
- `~/.cache/unspun-r1-retention/unspun-r1-observe-v3-75c0374.tar`，SHA256 `adb0a531a9bd46ea99b2cb08f460bf09988779a0d77bcdbc4564a53240ca066e`；summary 和逐字段审核脚本同目录。保留采集器已经完成，不再等待新一轮。
- 原窗口 `unspun-r1-observe-0a1a5ee.tar` 及旧 612 记录不改写；新窗口不是旧失败的替换。
- `~/.cache/unspun-r1-reconciliation-oct17/` 有安全的 `read_key_pre_rollout.py` 和 `read_production_pre_rollout.py`。前者仅输出白名单 provider 计数、从已有 SSH 内存加载 key；后者只读 SQL/实际镜像/阶段/worker。不要 cat `.env` 或输出凭证。

推送/拉取若 SSH origin 失败，沿用清除代理的 HTTPS + `gh auth git-credential`。PR 描述写临时文件用 `--body-file`；不重写已发布历史。CI 必须核对选中检查和 required-checks，main 还要确认实际 deploy 步骤与目标版本，不能因某个 job skipped 误判已部署。

最终只读核对 `2026-10-18T03:03:22Z`：生产仍为 `6cf450b`，旧/R1 worker 均未运行，R1 task/BR 为 0，22 路阶段全关、预算策略/carry 均尚未初始化。[交接时生产证据](https://github.com/LinsRock/unspun/blob/eb5b19f749c8316174e9cc5f6e838d7bbb0aec85/docs/acceptance/r1-production-rollout/pre-activation-production.json)明确本 session 没有启用或新增生产费用。
