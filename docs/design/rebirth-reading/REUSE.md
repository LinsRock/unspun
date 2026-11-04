# 首次复用验证：结论与选型边界

2026-11-04，按[架构对照方案](../../superpowers/specs/2026-11-04-rebirth-architecture-comparison.md)做有界验证。**目前建议优先 B：自己实现 Unspun 业务层，选择性吸收 AIHOT 工具与测试；A 整体 fork 保留为候选，未被实测排除。** 本次没有搭建两个产品，也没有证据估算总工期或复用比例。

## 已运行的证据

从固定提交 [AIHOT cd424b0](https://github.com/KKKKhazix/AIHOT/tree/cd424b0a513c7c8535b6f291b106a3086d6b75bf)实际提取日期工具、两个格式化依赖及原测试，保留 MIT 版权与许可。Node v26.12.1 下，UTC／上海两种宿主时区均 **30/30 通过**；其中 20 项是保留的上游纯日期测试、5 项是新增中文跨领域日期场景、5 项是发布策略边界。可复现命令、文件与改动、遗漏测试见[试验说明](experiments/README.md)。没有启动上游系统或发出来源、模型请求。

日期解析可以独立复用，且原发“仅日期”和真实零点没有混为一谈。实际限制也保留在测试中：日期解析器会接受句子里的事件日期和“更新于”日期，不能自行证明原发时间；中文数字日期仍未知。它不是完整来源适配器，真实中文来源覆盖与时效仍未测。

另将上游 `publish.ts` 的 selected 谓词原样提取后，新增独立阅读就绪／去重状态的纯策略适配。同一 pending 合格文章在原谓词下不入选，适配后独立入选且不确认 pending 事件关系；撤回与关系撤销也有内存场景验证。这是**可执行的局部适配**，不是 AIHOT 发布事务或完整业务回归通过。

## A 与 B 的决定性差异

下表除上面明确运行的两项外，均为固定提交的静态审阅；所列上游集成测试只阅读，**没有运行**。

| 要求 | A：整体 fork 的具体接入点与缺口 | B：自己的业务层 + 选取组件 |
| --- | --- | --- |
| 归组 pending 的独立文章可精选 | [publish.ts](https://github.com/KKKKhazix/AIHOT/blob/cd424b0a513c7c8535b6f291b106a3086d6b75bf/packages/backend/src/publication/publish.ts#L240)还负责 `articles/analyses/editorial_overrides/fact_articles/publications`、行锁、fact 席位、ledger 与队列；`rules.ts`／`scope.ts`规定读取资格。不能只去掉 grouping 条件，必须持久保存独立就绪／去重依据并检查所有出口。`independentSelectedSources` 只保留来源独立卡，仍受归组完成门槛约束 | 独立文章资格与事件关系分别建模；已验证纯边界可表达，但材料检查、写入和恢复仍需真正实现。日期工具可带原测试保留 |
| 精选与热点共用事件身份 | [site.ts](https://github.com/KKKKhazix/AIHOT/blob/cd424b0a513c7c8535b6f291b106a3086d6b75bf/packages/contracts/src/site.ts#L81)的 TimelineCard 是代表文章 + fact group；HotEntryView 是 story。`timeline.ts` 用 `f{factId}`／`a{articleId}` 聚合，`hot.ts`验证 story 现存证据。需确定 event 对应 story、progress 对应 fact，再改精选投影、类型筛选、游标绑定、缓存与详情链接；不能靠改卡片标签完成 | 从开始采用 event/article/video 联合卡片，热点引用同一 event。收益是业务契约直接；完整数据库关系及分页一致性仍未由本复用试验证明 |
| 服务端偏好、跨设备与撤销 | [local-state.ts](https://github.com/KKKKhazix/AIHOT/blob/cd424b0a513c7c8535b6f291b106a3086d6b75bf/apps/web/app/lib/local-state.ts#L1)依赖 React、`window.localStorage/sessionStorage`、storage 事件；收藏／已读导入合并不等于兴趣偏好或服务器冲突控制。没有找到可诚实当作服务端偏好核心提取的纯边界，因此本项没有伪造“复用成功” | 需要新建持久偏好、版本冲突、撤销和排序契约；同目录阅读原型可演示相应行为，但不算 AIHOT 复用证据或生产存储验收 |
| 去掉刊物且保住运行基础 | `apps/worker/src/schedules.ts`含 `reports.compose`；还需清点报告后台、告警及公开出口。来源任务、事务入队、恢复、备份等既有能力可能值得保留，但本次没运行 | 不带入刊物业务；任务、费用未知状态与恢复机制仍是需要补齐的工程工作，不能因页面可读而省略 |

发布适配后至少要重验 [`selected-news-gate.test.ts`](https://github.com/KKKKhazix/AIHOT/blob/cd424b0a513c7c8535b6f291b106a3086d6b75bf/tests/selected-news-gate.test.ts)、[`independent-selected.test.ts`](https://github.com/KKKKhazix/AIHOT/blob/cd424b0a513c7c8535b6f291b106a3086d6b75bf/tests/independent-selected.test.ts)、`publication.test.ts`、`timeline-group-scope.test.ts` 与 `hot.test.ts`；其中“所有 pending 内容都不得精选”的断言需要按新规则拆分，不能整项删除。这些测试涉及 PostgreSQL、pg-boss、API 与模块安装，本次没有为了运行它们启动完整系统。

## 技术栈与下一步判断

**TypeScript + React/Vite + Fastify + PostgreSQL + pg-boss 仍是有条件候选，不是本试验的定案。** 日期工具直接运行说明语言一致确有移植便利，但两个格式化依赖和一个谓词不足以证明更换整个后端值得；本次也没测 Fastify、PostgreSQL 或 pg-boss。若后续实际保留的来源解析主要来自现有 Python，Python + FastAPI 仍应比较，不维护两套后端。

本轮选型建议是采用 B 进入下一批正式设计，按 Unspun 的业务对象组织代码，并逐组件保留经过验证的 AIHOT 工具。这是基于已知适配范围的工程判断，不是 B 总成本更低的实测结论；不需要再并行造两套完整产品。

若后续出现支持 A 的新证据，再核验以下集成条件：独立阅读资格能进入真实发布事务；event 身份贯通精选／热点且类型分页正确；服务端偏好可重启保存并处理冲突；刊物停止后无残留任务／出口。若这些差异集中且原有恢复、撤回与读取测试可保留，A 仍可能合适。本批交付 B 的选型建议与阅读原型，正式仓库和完整技术栈仍需结合用户试读确定。来源质量、自然新增、真实热度及费用保护仍未完成。
