# 技术决策日志

记录重要技术决策与理由，防止后续 AI 会话在不知情的情况下推翻既有决策、来回摇摆。

- 新决策追加在最上方，编号递增。
- 推翻旧决策时不删除原条目，在原条目开头标注「已被 D-xxx 取代」。
- 只记"会影响后续方向"的决策；日常实现细节不记。

---

## D-009 · 2026-10-09 · 前端外链只放行 http(s) 协议

事件卡片的原文链接来自外部抓取的 RSS 源，属不受信输入。`EventCard.tsx` 的 `safeHref` 只放行 `http:`/`https:`，其余不渲染为链接，防止恶意源用 `javascript:` URI 注入脚本。配套：抓取入库侧也应校验 URL 协议（见 M1 任务板 A6），前后端双层防御。

## D-008 · 2026-10-09 · 无官方 RSS 的中文源推迟到 M2

财新、澎湃、界面、联合早报、机器之心、36氪没有官方 RSS。M1 只用官方 RSS（28 源：22 英 6 中，已逐一验证可用），上述源等 M2 自建 RSSHub 后再接入。不在 M1 引入第三方镜像源，避免稳定性和合规风险。

## D-007 · 2026-10-09 · 每次 LLM 调用记账入库

`unspun.core.llm` 的每次调用把 token 用量与成本写入 `llm_usage` 表，日报据此汇总当日花费。理由：M1 验收有月度折算 ≤$50 的预算红线，花费必须随时可观测，而不是月底对账单才发现超支。

## D-006 · 2026-10-09 · 日常调参只改 config/，不改代码

聚类相似度阈值（0.72）、排序时间衰减半衰期（24h）、评分权重等全部在 `config/scoring.yml`；源清单在 `config/sources.yml`。理由：调参是 M1 试运行期的高频操作，改配置不改代码意味着无需动测试和评审逻辑。

## D-005 · 2026-10-09 · 聚类采用增量最近质心 + 余弦相似度

每篇新文章与现有事件质心算余弦相似度，超过阈值并入最近事件，否则新建事件。理由：MVP 优先选最简单、可解释、可调参的方案；是否需要重聚类、事件合并/拆分，等 M1 试运行的真实数据说话，不提前过度设计。

## D-004 · 2026-10-09 · 模型分档：摘要用 flash-lite，重要性评分用 flash

摘要默认 `google/gemini-2.5-flash-lite`（量大、要求低、取最便宜档），重要性评分默认 `google/gemini-2.5-flash`（质量要求高一档）。均可用环境变量覆盖：`UNSPUN_SUMMARY_MODEL` / `UNSPUN_IMPORTANCE_MODEL` / `UNSPUN_EMBEDDING_MODEL`。

## D-003 · 2026-10-09 · embedding 用 qwen3-embedding-8b，MRL 截断到 1024 维

数据库 pgvector 列宽固定 1024 维；embedding 取 `qwen/qwen3-embedding-8b`（中英混合语料效果好、OpenRouter 可用、约 $0.01/M tokens），MRL 截断到 1024 维后做 L2 归一化。固定列宽的理由：换 embedding 模型时不必迁移表结构。

## D-002 · 2026-10-09 · LLM 与 embedding 全部走 OpenRouter

只维护一个 `OPENROUTER_API_KEY`，不接 OpenAI，不在 VPS（2核4G）本地跑任何模型。理由：单一账单与花费上限、模型可随时切换、小机器只做管道不做推理。

## D-001 · 2026-10-08 · 部署链路：CI 构建 → GHCR → SSH over Cloudflare Tunnel

镜像由 CI 构建并推 GHCR；部署用 cloudflared SSH（Access service token 认证）进 VPS 执行 `deploy/deploy.sh`。VPS 不开放任何入站端口，Web 仅经 Tunnel + Access 暴露，生产密钥只存在于 VPS 的 `~/unspun/.env`。
