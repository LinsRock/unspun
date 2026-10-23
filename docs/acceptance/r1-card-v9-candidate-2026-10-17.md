# R1-09 评论类型候选修正 · 原失败与后续通过记录

当前结果：v9 卡片及 v5 导读已完成真实回归、独立留出与费用对账，达到原技术门槛，见[最终报告](r1-final-content-quality-2026-10-17.md)。下文保持此前阻塞截面，原失败及未知费用不删除。

历史截面：此分支仅为 `r1-card-v9` 候选，尚未合并或部署，G1 最终质量未通过。修改前已登记[原版本、输入及不变期望](../evaluations/r1/card-v9-candidate.json)：C12 的原冻结材料类型为“评论”，既有 `declared_genre` 规则要求 `opinion`；原已知物理响应却返回 `genre=commentary`，仅此字段触发 `ValidationError`。这是实际格式失败，不能只写成预算延期。

候选澄清来源评论/社论应输出已有枚举 `opinion`，并保留原来的观点归属；卡片策略版本升为 v9。没有给输出 schema 添加别名，没有重写旧响应/标签，也没有放宽中文、引文、归属或准入规则。[只读旧响应检查](https://github.com/LinsRock/unspun/blob/eb5b19f749c8316174e9cc5f6e838d7bbb0aec85/docs/acceptance/r1-card-v9-candidate/baseline-check.json)确认该错误响应在候选下仍被严格拒绝。是否能让新模型响应遵守契约，必须用真实评测确认，不能由此推定成功。

另建并迁移 `unspun_r1_genre_candidate_tests_20261017` 至 `000015` 后，[完整 858 项通过、零跳过](https://github.com/LinsRock/unspun/blob/eb5b19f749c8316174e9cc5f6e838d7bbb0aec85/docs/acceptance/r1-card-v9-candidate/technical-checks.json)；Ruff、格式、严格 Pyright 及旧 40 事件回归通过。这些是实现/恢复/API 回归，不能替代模型质量。导读仍为 v4，但其输入指纹包含卡片版本，最终组合的导读质量及费用也须复核。

上述候选技术检查时新增付费调用、费用核对写入均为 0；真实评测仍用原 `unspun_quality_r1_20261016` / $0.60 分配和原 Flash Lite / Flash 模型。T01–T06 未加载或调用，旧 v8 失败保持原记录，未知预留按下文凭证结算或继续保留，不补零。待请求级费用核对允许继续后，按原冻结输入/阈值完成当前候选回归、新留出评测、导读及单位成本；通过前 PR 保持草稿，不合并此提示变更或启用生产处理。

后续真实评测：用户补充凭证已使原两笔未知按 $0.0009326 实费结算，另外三笔保留未知。随后在原库、原模型/额度运行 v9 原冻结回归 21 例：3 例依原规则拒绝、18 例技术错误（第一条审核连接中断，其余审核预算延期）。18 次实际生成草稿均通过严格 schema，C12 实际返回 `opinion`；尚无审核完成的 ready 结果，因此不能据格式改正声称质量通过。新增物理调用 19 次，已知 $0.0068895，新未知 Flash 审核 `bdbdbb331ac546eb84d6f42b502f362b` 预留 $0.170674。T01–T06 私有材料未加载/调用，用户评分未改。见[逐例指纹、调用和格式检查](r1-card-v9-candidate/first-attempt.json)。

这次网络错误发生在响应头账务修复前；[PR #86](https://github.com/LinsRock/unspun/pull/86) 已独立补保存响应头 ID 的能力。待取得本次已丢失的 generation ID 并结算后，复用上述同指纹生成响应，继续完整审核、新留出及导读。PR 仍保持草稿，不放宽原门槛、不合并提示词候选或启用生产处理。
