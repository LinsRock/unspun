# 文档入口

按当前任务选读，不要递归加载整个 `docs/`。工程约定见 [CLAUDE.md](../CLAUDE.md)。产品交付状态统一看 [R2 任务板](tasks/r2.md)，不从历史计划推断当前进度。

| 要做的事 | 阅读入口 |
| --- | --- |
| 查产品目标或调整需求 | [产品定义](product-definition.md)、[需求](requirement.md) |
| 查交付顺序和下一阶段 | [路线图](roadmaps.md) |
| 实施或修复 R2 功能 | [R2 任务板](tasks/r2.md)中对应任务，再读该项链接的规范 |
| 处理 R2-06 验收或继续执行 | [当前交付与剩余门槛](acceptance/r2-06-completion-2026-10-22.md)、[本批契约](superpowers/specs/2026-10-22-r2-06-completion.md)；当前 3/4、真实语义未测、付费停止 |
| 调整来源 | [来源计划](source-plan.md)，运行配置另看 `config/sources.yml` |
| 清理文档或开发资源 | [清理任务板](tasks/cleanup.md)中对应 CL 项 |
| 修改架构或既有约定 | 搜索[决策日志](decisions.md)中的相关 D 编号，仅阅读有关条目 |
| 部署或回退 | [部署配置](deploy-setup.md)、[工程约定](../CLAUDE.md)和 `deploy/` |
| 追查历史、评测、验收或原型 | [历史索引与恢复](archive/README.md)；只打开要核对的原件 |

日常搜索使用 `rg <关键词> server web config docs`。`docs/.ignore` 让旧计划、原型、评测与验收材料退出默认递归搜索；这些文件仍被 Git 跟踪，代码和测试可以按原路径读取。需要历史材料时用 `rg --no-ignore <关键词> docs/acceptance` 等明确范围，或直接打开文件。不要把 `--no-ignore` 用于整个仓库。

维护规则：任务板只留验收清单、简短状态和证据链接；完整日志、JSON、截图留在对应证据目录。已结束的交付不要继续往 `CLAUDE.md`、需求和路线图复制过程记录。新增证据应复用已有入口，避免产生多份完整交接稿。
