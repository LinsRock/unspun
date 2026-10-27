# CL-05 第一批：保留规则、只读候选与隔离验证

依据 [D-031](../../decisions.md#d-031--2026-10-19--分阶段安排旧链路文档及无用过时数据清理)和[清理任务板](../../tasks/cleanup.md)。本批交付清理准备，**生产实际批次仍待 R2-11 后续验收**。不启动 CL-04/06、R3 或定时清理。

## 当前授权与保护边界

- 从 `origin/main 4042f20` 独立开发。未合并的 [PR #143](https://github.com/LinsRock/unspun/pull/143) 与 [PR #144](https://github.com/LinsRock/unspun/pull/144) 的当前保护登记继续有效。原主干中的“启用准备、等待授权”是旧截面；实际有限启用交接见 [#143 固定版本](https://github.com/LinsRock/unspun/blob/6a1592cd8e32157860aeebf6810b3a8c6c4c2a44/docs/acceptance/r2-11-reading-enablement-2026-10-26.md)，最新暂缓与资源范围见 [CL-03 固定交接](https://github.com/LinsRock/unspun/blob/1f2007fd640cfe4b9618db086f49ad6272cac88e/docs/acceptance/cl-03-local-cleanup-2026-10-27.md)。
- **R2-11 暂缓，8/12、原失败、全部接续脚本/结果/环境保持；“到时执行”不再是授权。** 不调用观察器或 mixed 探测，不改现网开关。
- 生产仅允许有界 `REPEATABLE READ / READ ONLY` 核对，无删除、归档、压缩、schema 变更。现有预览及 84 个 CL-03 保留库均禁止 apply；R2-04、冻结输入、原累计评测、未知预留、paid-stop、用户空评分保持。
- 本批主动生成、embedding、付费重试、提供方查询均 0；原 R1 消费者自然活动不算本批调用，也不宣称整个窗口零费用。不购买额度、不绕过 CI。

## 数据分类与保留规则

以下是本批可执行的保留规则。推荐时效只影响推荐窗口；年龄、任务终态、停止处理和重复文本都不单独授权删除。未列入唯一可处理类别的数据，清理上限均为 **0**。

| 类别 | 保留依据、期限与摘要 | 本批载体 / 恢复 |
| --- | --- | --- |
| 内容、事件、观点、日报及历史可读版本 | 原时间/来源、公开与历史阅读、离线日期、必要引用；不按推荐过期设删除期，保留至历史阅读替代方案单独验收 | 原表与原 ID 保留；不能只保留摘要替代阅读正文 |
| 规范身份、别名、URL、观察和来源归属 | 去重、规范身份解释、来源诊断与分母；保持原行和历史时间，无本批到期日 | 原表保留；不合并 ID，不重写 canonical 关系 |
| 当前材料、派生、向量、成员判断、话题版本、审核/合成证据 | 当前指针、FK、JSON 输入/证据/版本、引用闭包与冻结依赖；被引用即保留，撤回/失败版本仍可能有价值 | 原件保留；不以重抓、embedding 或模型生成恢复 |
| 反馈、兴趣、Reader 变更及请求回执 | 撤销、幂等、CAS 版本与用户原义（包括 null）；长期保留，无本批删改 | 原表保留，核对行哈希与读取结果 |
| 任务、尝试、discovery batches、配额及诊断 | 活跃任务恢复；终态仍承担去重键、配额占用、原失败、成本分母；暂无已验收等价摘要 | 全部保留，不按 completed/failed 或日期清空；汇总/分层归档需另批验证 |
| 真实费用、物理调用、usage、预算、carry、费用审计、未知预留 | 逐笔审计和累计池；未知不结零、不释放，历史 reserved 字段不冒充当前 hold | 原表与凭证长期保留，包括 settled-without-result 和原失败；不查询提供方补证 |
| 空正文、验证页、受限/失败响应 | 来源问题、冻结反例与必要失败重现；本批不具备“必要样本已足够”的删除证明 | 全部保留，不以重复或旧日期删除失败原件 |
| **同一内容下的旧成功材料等价副本** | 本批唯一可验证类别；至少保留 **30 天**，满足下述全部谓词才是候选。30 天是保守下限，不是生产生命周期效果结论 | 新隔离库内删除完整旧行；删除前将完整原行、ID、时间与证据保存为带校验和的 JSON，原 keeper 不改 |
| 冻结文件、评测和开发库/缓存、备份 | 沿用 CL-03 精确保留登记；无外部用途证明则 pending。现有生产本地 14 天备份轮替仅为事实，不视作已验证恢复 | 不移动/改字节、不清库；新隔离库及恢复 JSON 保留到本批审查结束且恢复后至少 30 天，再另行登记处置 |

## 唯一清理谓词与引用边界

目标仅为 `content_materials` 的完整行，必须同时满足：

1. `retrieved_at <= transaction_timestamp() - interval '30 days'`；`access_status='ok'`、`scope != 'none'`、`paragraphs` 非空。失败/空材料一律排除。
2. 同一 `article_id` 的 **当前材料**存在，且两行除 `id/input_fingerprint/retrieved_at` 外每个字段 JSONB 等价。正文、顺序、metadata、scope/completeness、URL、response、extractor/schema version 和 evidence 均比较。不是仅比 text fingerprint，也不跨身份去重。差异的身份、输入指纹和时间仍完整进入恢复文件。
3. 从数据库 catalog 枚举所有指向材料的 FK，逐条核对复合 owner/material 外键；任何引用都排除。当前 schema `000021` 有 4 个此类 FK。
4. 枚举 public 中全部 JSON/JSONB 列（当前 50 列），保守查找材料 ID、owner ID、input/text/response 指纹，包含嵌套 evidence、input_snapshot、版本、数组、字符串和映射键。对当前材料本行以外的行检查。数值重号等匹配可能是假阳性，**一律保留**，不把“没有 material_id 键”理解为没有引用。版本通过材料 FK、owner 与指纹共同保护；旧版本的引用不会因状态而跳过。
5. 任务和物理费用还查 owner、object_key 及输入/请求指纹；所有状态都受保护，不只检查 running。外部文件/冻结/必要失败审查必须有逐对象完整行 SHA-256 和依据；缺失或过期即 pending。本批真实数据均没有获得外部解除保护。
6. apply 不接受从旧 CL-00 清单直接导入删除目标，也不接受 dry-run 结果作为永久授权。显式 ID 和外部 clearance 在写事务内重新核对，当前行/引用有变化就整批拒绝。

已知 schema 以外的版本/用户 schema 拒绝；任何超时、查询失败或截断都不产生删除批准。该保守扫描不是通用引用解析器，也不允许处理其他类别。

## 有界入口与隔离注册

工具：[server/eval/cl05_retention.py](../../../server/eval/cl05_retention.py)。位于离线工具目录，不注册 API、worker 或调度。显式从 `CL05_DATABASE_URL` 读取 DSN，缺失即失败，不回退到应用生产配置。常规运行默认 dry-run。

- 每次只读最多 50 个非当前材料，按 ID 排序，额外取 1 行判断截断；`--after-id` 显式翻页，不自动循环。本批生产最多 4 页/200 对象；实际共 4 页/114 次对象核对，含终版两页复核，共 57 个唯一对象。每页独立 RR 只读截面，不拼成同一瞬间快照；不覆盖之后的自然新增。
- 单 SQL 5 秒、锁等待 1 秒、空闲事务 30 秒、整个事务 120 秒；候选计算在对象间另检查 90 秒预算。任何超限停止。
- apply 必须显式指定 1–10 个不同正整数 ID；完整原行规范 JSON 合计不超过 1 MiB。恢复同样有行数和字节上限。行数/JSON 字节均不是文件系统释放量。
- `--create-isolation --registry <新路径>` 只在明确 `127.0.0.1` 上创建随机 `unspun_cl05_lab_<20 hex>`、`template0` 空库；没有注册既有库、force 或导入生产功能。工具固定库名/OID/集群标识/服务端地址端口/随机数据库注释。迁移只运行在返回的新库，至 `000021`。
- apply/restore 同时核对显式 loopback DSN、随机命名、注册中的库身份和 schema；任何生产、现有预览/评测、同名重建或其他集群都不能复用登记。注册文件不保存口令。恢复文件以 0600、新建且不覆盖方式写入，fsync 文件与目录并读回验证。
- 新隔离库不得接 worker、预览、提供方密钥或付费处理。写事务以稳定顺序锁住所有用户表，READ COMMITTED 下重查，使先提交的 FK/JSON/任务引用可见；争用超时失败。锁仅用于隔离实验，**不是生产并发清理方案**；写入在提交后才来的任意无 FK JSON 引用仍需未来生产写入协议共同保证。

```bash
# server/; set CL05_DATABASE_URL locally without printing credentials.
uv run python eval/cl05_retention.py
uv run python eval/cl05_retention.py --create-isolation --registry /private/tmp/cl05-new.json
# Point UNSPUN_DATABASE_URL at the exact newly returned database, then migrate it.
uv run alembic upgrade 000021
# Register per-ID row_sha256 and an actual external-review basis in clearances.
uv run python eval/cl05_retention.py --registry /private/tmp/cl05-new.json --ids 810001
uv run python eval/cl05_retention.py --registry /private/tmp/cl05-new.json \
  --ids 810001 --apply --archive /private/tmp/cl05-original.json
uv run python eval/cl05_retention.py --registry /private/tmp/cl05-new.json \
  --restore --archive /private/tmp/cl05-original.json
```

示例 ID 仅为合成验证对象。不得复制示例作为实际库候选；保留库永远不在此入口写入范围。

## 回滚、恢复及验收

所有删除在一个事务内完成。恢复文件必须先落盘，归档失败就不删除；DELETE/约束/提交失败回滚，文件保留。提交结果不明时从文件核对原行，不盲重试或覆盖文件。重复 apply 对已不存在的指定行返回 0；重复 restore 对相同原行返回 0。

restore 校验 SHA-256、库身份、schema 和批次上限，通过 `jsonb_populate_record` 恢复原 ID、时间、正文、证据与指纹，不调用任何抓取/生成；原行存在但不同则整批拒绝，不能覆盖新状态。恢复事务失败不留部分恢复。生产备份恢复能力本批未获得验收。

验证必须覆盖：默认只读、实际隔离删除、重复执行、新增 FK/嵌套 JSON/版本引用、活跃和终态任务、行/字节/环境边界、锁争用、备份失败、删除失败回滚、恢复损坏/冲突/幂等，以及非空历史阅读、身份、反馈/空值、任务去重/恢复、配额与费用/预留保持。[结果与候选入口](../../acceptance/cl-05-retention-2026-10-27.md)只保留必要清单和简短结论，不提交测试日志、整库导出或整机快照。
