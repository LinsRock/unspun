# R2-06 第一批：关闭的成员处理链

基线 `ed86474`。本批仅交付工程处理链、共享队列/账务和恢复证据；真实模型精度、覆盖、后台纠错和启用属于下一批，R2-06 整体不完成。R2-04 观察资源不变，不接手启源。无页面、公开话题、进展生成或 R2-07+。

## 处理与版本

显式内部入口在当前合格 R1 规范内容上排 `topic_recall`，后继 `topic_judge`、`topic_review` 共用现有 paid 队列、单消费者槽和租约。全局 `r2_member_processing_enabled=false`；关闭时无入口排队、无 handler，也拒绝新阶段付费。阅读和原卡片链不自动排话题任务。

召回先按领域 SQL 限定至 32 个现有 active 话题，每个最多取两个当前有效成员，以材料中的合格主题词作主体线索、原发时间距离作排序依据，最多 12 个话题进入向量阶段、最多 4 个后继判断。旧背景及未知时间有保留路径；处理时间不冒充发生/报道时间。此有界采样不声称完整召回。空候选只记录独立内容，不建话题。

新向量追加存储；键覆盖规范内容/别名身份、当前材料实际输入、来源发布边界、合格 card/审核快照、embedding 输入契约/实际截断文本、模型及维度。只复用键完全相同的新版本，不读取 Article.embedding 或旧 Event.centroid。每份向量 checkpoint 必须通过当前租约和输入校验，重启复用已提交向量及统一账本的已知响应。

候选保存话题 revision/定义、所选成员 revision、材料/身份/来源输入及向量版本。任务去重覆盖输入、候选集合和判断/审核契约及模型。相似度仅决定候选顺序；判断明确区分 same_event、same_issue、background、opinion、explanation、reprint、independent；uncertain 永远保留独立。有关联的结果必须引用待判断材料及候选锚点原文，审核必须明确批准同一判断指纹且无问题；不是用分数阈值自动归并。

审核后重新检查任务租约、当前输入指纹、候选话题 revision/材料/来源及契约，才通过 R2-05 mutate_topic CAS 写入。冲突结果保留为 stale，不修改新 revision；不自动覆盖已有 active/inactive 成员。审核失败、独立或不确定不影响原独立阅读。多话题各自独立 CAS。

## 账务与分配

新增 stage：topic_embedding/embed（原 embedding 模型）、topic_judgment/judge（原 summary 模型）、topic_review/review（原 viewpoint 模型、grounding 用途并受原 $0.40/24h 审核上限）。每笔仍写 BilledRequest/LlmUsage，绑定原 task/attempt/article/source/object 和逻辑输入；没有平行账本。重试保存每笔物理费用，unknown 保留完整 reservation，不因租约过期释放。

代码注册新阶段硬上限，但初始化继续使用原 STAGE_CAPS，不改已有政策。新阶段在生产和评测均要求正的显式分配；生产启用还要求 legacy=0，card/guide/embedding 与三个新阶段的分配和不超过原 $13.50。建议下一批审查方案为 card=9.50、guide=2、embedding=1、topic_embedding=0.10、topic_judgment=0.45、topic_review=0.45，合计 $13.50；这是登记方案，**本批不写政策、不启用、不付费**。原项目 $15、原累计评测 $1.50、模型及提供方/未知费用保持。不得以 legacy/card 或 embedding 自动分类绕过新阶段。

## 执行与验收计划

1. 新建迁移隔离库，先跑基线并确认本轮源码导入；增量 Alembic 只加向量和判断历史表，downgrade 失败关闭保留历史。
2. mock 全部模型/外部 HTTP，验证并发/幂等、租约过期/晚返回、重启、材料/身份/来源变更、CAS 冲突、预算延期、重试及未知费用和旧路径。
3. 完整相关回归、Ruff/Pyright、schema 漂移、旧排序及冻结清单；冻结输入回放仅算工程验证，质量/覆盖留空。
4. 带旧业务/账务/未知预留及新历史做 upgrade/repeat、完整 dump/restore、固定镜像迁移兼容验证。保留库、备份和失败原件。
5. 自审差异和调用方；同 PR 更新任务板及证据，CI 通过后合并，核对实际 Deploy、源码/schema、阅读/账务/观察边界以及生产开关/新任务/新费用均关闭或为零。

## 第二批召回契约 v2

上述第一批 v1 范围与证据保留。第二批按[真实评测契约](2026-10-20-r2-06-member-evaluation.md)修复空 card.topics、UUID 前置截断、失效首锚点及未知/背景竞争；成员总版本升为 `r2-member-v2`，不改变 R1 card/guide、embedding 输入、模型、语义判断或审核/CAS 门槛。原 v1 的有界召回描述不再代表当前召回算法；旧行为由固定源码对照保留。生产开关与新阶段分配继续关闭。
