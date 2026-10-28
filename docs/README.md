# 文档入口

按当前任务选读，不要递归加载整个 `docs/`。工程约定见 [CLAUDE.md](../CLAUDE.md)。产品交付状态统一看 [R2 任务板](tasks/r2.md)，不从历史计划推断当前进度。

| 要做的事 | 阅读入口 |
| --- | --- |
| 查产品目标或调整需求 | [产品定义](product-definition.md)、[需求](requirement.md) |
| 查交付顺序和下一阶段 | [路线图](roadmaps.md) |
| 实施或修复 R2 功能 | [R2 任务板](tasks/r2.md)中对应任务，再读该项链接的规范 |
| 体验或继续 R2-10 页面 | [页面与隔离契约](superpowers/specs/2026-10-26-r2-10-reading-pages.md)、[预览与交付记录](acceptance/r2-10-reading-preview-2026-10-26.md)；页面体验、PR/CI 与关闭部署已完成；当时未切换入口，后续状态见 R2-11 |
| 查看暂缓的 R2-11 | [有限范围契约](superpowers/specs/2026-10-26-r2-11-reading-enablement.md)、[当前排期与保留交接](acceptance/r2-11-reading-enablement-2026-10-26.md)；保留 8/12 计数、接续脚本及全部结果，不继续探测、不改现网 |
| 实施 R2-08 混合后端 | [冻结契约](superpowers/specs/2026-10-23-r2-08-hybrid-feed.md)、[首批工程记录](acceptance/r2-08-hybrid-feed-2026-10-23.md)；入口默认关闭，用户效果与启用另验 |
| 实施 R2-09 话题偏好 | [目标/API 契约](superpowers/specs/2026-10-23-r2-09-topic-preferences.md)、[后端交接](acceptance/r2-09-topic-preferences-2026-10-23.md)；页面、主观效果与启用另验 |
| 实施 R2-07 进展与概况 | [当前契约](superpowers/specs/2026-10-23-r2-07-progress-overview.md)、[首批工程记录](acceptance/r2-07-progress-overview-2026-10-23.md)；真实质量与启用尚未完成 |
| 处理暂缓的 R2-06 验收 | [当前交付与剩余门槛](acceptance/r2-06-completion-2026-10-22.md)、[本批契约](superpowers/specs/2026-10-22-r2-06-completion.md)；当前 3/4、真实语义未测、付费停止 |
| 调整来源 | [来源计划](source-plan.md)，运行配置另看 `config/sources.yml` |
| 清理文档或开发资源 | [清理任务板](tasks/cleanup.md)中对应 CL 项 |
| 修改架构或既有约定 | 搜索[决策日志](decisions.md)中的相关 D 编号，仅阅读有关条目 |
| 部署或回退 | [部署配置](deploy-setup.md)、[工程约定](../CLAUDE.md)和 `deploy/` |
| 追查历史、评测、验收或原型 | [历史索引与恢复](archive/README.md)；只打开要核对的原件 |

日常搜索使用 `rg <关键词> server web config docs`。`docs/.ignore` 让旧计划、原型、评测与验收材料退出默认递归搜索；保留文件仍被 Git 跟踪，代码和测试可以按原路径读取；已移出的过程产物从固定 Git 历史恢复。需要历史材料时用 `rg --no-ignore <关键词> docs/acceptance` 等明确范围，或直接打开文件。不要把 `--no-ignore` 用于整个仓库。

维护规则：任务板只留验收清单、简短状态和证据链接；数据按[验收材料保留规则](acceptance/README.md)保存最小必要原件，普通日志、CI 状态及过时快照退出当前版本。已结束的交付不要继续往 `CLAUDE.md`、需求和路线图复制过程记录。新增证据应复用已有入口，避免产生多份完整交接稿。
