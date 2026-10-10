# M2 内容质量优化设计

用户于 2026-10-10 批准“证据约束 + 分歧分类 + 固定样本评测”。保留摘要 flash-lite / 观点 flash，不自动增加审核模型。此任务补齐 T10 内容质量缺口，不替代七天生产观察、手机实测与源数量决定。

## 摘要与共享证据

新增 Article.summary_grounding JSONB（可空、增量迁移），结构 `{version: "summary-grounded-v1", status: "grounded"|"limited", facts: [{text, quote}]}`。LLM 输出 `{title_zh, facts:[{text,quote}], content_quality:"sufficient"|"limited"}`，不再要求固定句数。quote 必须来自传入的原文标题/正文，使用 Unicode 与空白归一后校验；不允许从旧摘要取得证据。不凭标题补机构、同比、因果或具体数字；少信息时允许零 facts。零有效事实使用原始标题作最小摘要并标为 limited，避免永久重试或写入编造摘要。仅结构存在/真实引用并不能证明中文事实受原文支持，语义质量另行评测。

`unspun.core.grounding` 提供 `normalize_text(text)`、`quote_in_source(quote, source)`、`supported_years(text, source)`、`article_source_text(article, max_chars=6000)`。年份校验只限制额外出现的四位年份，允许原文明示的历史年份；不将发布时间当成事件发生日期。summary_grounding 留存事实与引用，source text 是原始标题 + 正文而非 title_zh/summary_zh。

## 观点

输入包括每源原始标题、published_at、已验证事实及相关原文片段；旧摘要作为不可信辅助，不能作证据。摘要优先作为片段选择的线索，限制输入长度，不自动发送整篇全文。每条说法 `{article_id, claim, evidence_quote}`，证据必须匹配对应源的实际传入片段；每种差异 `{point, claim_indexes, kind}`，kind 为 factual_conflict / viewpoint_difference / coverage_difference / temporal_update / uncertain。只有同一对象、时点、统计口径的互不相容陈述才称事实冲突；未提及、备选计划/最终决定、币种与时点变化必须保守处理。分歧的额外年份需得到关联来源支持。无足够证据时允许空比较，缓存不足结果防止每轮付费重试。

缓存指纹加入实际输入、来源名称、模型和生成版本，保持排序稳定。候选筛选必须能发现内容变化及旧生成版本；成本仍受每轮调用上限约束。旧观点按兼容 schema 读取，前端标出未附证据；新输出必须有证据。

## API 与界面

ArticleOut 新增可选 `content_quality: "grounded"|"limited"|null`；ViewpointClaimOut 新增 `evidence_quote: str|null`；ViewpointDisagreementOut 新增 `kind: str|null`。旧日报未含这些字段时默认 null，historical API 不依赖原文重读。观点卡片/日报支持展开“原文依据”，标明五种差异类型；旧数据标明未附证据，有限输入显示“信息有限”。所有外链沿用 safeHref，布局遵守 T-D1，用户本地体验后再提 PR。

## 修复与评测

固定 30 个案例，包含本次五个生产样本与清楚标为合成的边界/正常对照。评测报告记录证据有效率、保留说法数量、禁用断言/年份、分类正确情况、失败与 LLM 成本；不用全拒绝策略取得通过。先运行离线坏输出回归，再对同一输入比较旧/新真实模型输出并进行语义复查。真实调用在隔离本地评测库按 D-007 记账，不写生产业务数据；密钥不写入文件/日志。

提供显式 event-id 的受控修复命令，默认 dry-run，列出将重生成的文章和事件；执行模式通过正常 LLM/DB 模块更新摘要、embeddings、事件中心/代表摘要、重评分与观点。旧日报快照不修改。执行失败必须保留调用费用，不留下部分修复的混合状态；生产执行待代码经 PR 合入后再操作，本会话仅本地演示/评测。
