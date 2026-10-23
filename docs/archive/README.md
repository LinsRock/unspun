# 历史文档索引与恢复

这些材料按需追溯，不作为新任务的默认输入。当前入口见[文档指南](../README.md)。历史文档按需读取；过程数据按[验收材料保留规则](../acceptance/README.md)移入固定 Git 历史，现用冻结输入继续保留原路径和字节。历史结论不因归档改写。

| 历史范围 | 原件入口 | 当前替代或仍有效事项 |
| --- | --- | --- |
| 旧产品与路线 | [旧需求](../requirement-legacy-2026-10-15.md)、[旧路线](../roadmaps-legacy-2026-10-15.md)、[2026-10-15 重构建议](../implementation-proposal.md) | 当前[需求](../requirement.md)、[路线图](../roadmaps.md)与 [R2 任务板](../tasks/r2.md) |
| M1–M3 任务 | [M1](../tasks/m1.md)、[M2](../tasks/m2.md)、[M3](../tasks/m3.md) | 不再按旧顺序实施；独有未结事项映射见下文 |
| R0/R1 记录 | [R0](../tasks/r0.md)、[R1](../tasks/r1.md)、[R1 终验](../acceptance/r1-final-acceptance-2026-10-19.md) | R1 已结案，来源与用户评分缺口仍保留 |
| 旧设计与保留的计划 | [设计目录](../superpowers/specs/)、[计划目录](../superpowers/plans/) | 日期早于 R2 的规范仅供历史复现；当前规范由任务板定向链接 |
| 原型与截图 | [原型目录](../design/)、[前端设计约定](../../web/src/DESIGN.md) | 部分仍被样式、CI、预览和用户验收引用，原路径保留 |
| 评测、研究与用户反馈 | [评测](../evaluations/)、[来源研究](../research/)、[反馈](../feedback/) | 程序/测试依赖、冻结输入、原始评分及空值保留 |
| 验收与运行原件 | [验收材料规则与恢复](../acceptance/README.md)、[CL-00 盘点](../acceptance/cl-00-inventory-2026-10-20.md) | 现用输入、费用与必要失败原件保留，旧过程产物转 Git 历史；R2-06 当前交付看[最新验收](../acceptance/r2-06-completion-2026-10-22.md)，旧快照仅保留历史适用范围 |

未结事项沿用 CL-00 的承接：来源连续性及受限源交给 `source-plan.md` / R2-04；人工选材和排序反馈交 R2-11/R3；旧 M3 话题工作由 R2-05–07 承接；精选更新、七天运行和手机离线验收交 R3。M2 历史事件生产复验和旧日报七天记录仍未证实，分别交 CL-04、CL-06；旧手动纠错/配置覆盖中未获授权的部分继续 pending，不因归档自动结案。

## CL-02 删除清单（2026-10-23）

删除下列 9 份已被交付记录取代的逐步实施计划，均无现存 Markdown/代码引用、不在冻结清单内。它们位于 `docs/superpowers/plans/`；任务板中的实际验收、遗留缺口与用户结论继续保留，计划里未更新的勾选不再成为当前执行指令。

| 删除文件 | 保留的结果与承接 |
| --- | --- |
| `2026-10-10-t7-digest-pipeline.md` | M2 的 T7 验收及历史日报实现 |
| `2026-10-10-t8-digest-frontend.md` | M2 的 T8 页面验收 |
| `2026-10-10-t9-pwa.md` | M2 的 T9 本地验收；手机生产验收缺口保持 |
| `2026-10-10-t10-m2-closeout.md` | M2 结案决定及 [M2 验收](../acceptance/m2-2026-10-10.md)；未齐生产证据继续保留 |
| `2026-10-12-m3a-a1-implementation.md` | M3 的 A1 验收 |
| `2026-10-12-m3a-a2-history-implementation.md` | M3 的 A2 验收 |
| `2026-10-13-m3a-a3-implementation.md` | M3 的 A3 验收 |
| `2026-10-13-m3a-a4-implementation.md` | M3 的 A4 账务交付记录 |
| `2026-10-13-m3a-a6-implementation.md` | M3 的 A6 合并及 2026-10-14 后台重设计验收 |

清理前完整版本固定为 `1d92421`（已纳入 PR #131–133 的后台与进展链路交付）。被删计划和压缩前的 `CLAUDE.md`、R2 任务板均可由 Git 读取，例如：

```bash
git show 1d92421:docs/superpowers/plans/2026-10-10-t9-pwa.md
git show 1d92421:docs/tasks/r2.md
```

历史盘点 JSON 中的旧路径与哈希描述其登记版本，保持原样。搜索原件时明确指定目录，例如 `rg --no-ignore <关键词> docs/acceptance`；`.ignore` 仅控制常规搜索，不影响 Git、直接打开文件或测试读取。
