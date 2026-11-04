# AIHOT 最小可执行复用试验

2026-11-04。上游固定为 [AIHOT cd424b0a513c7c8535b6f291b106a3086d6b75bf](https://github.com/KKKKhazix/AIHOT/tree/cd424b0a513c7c8535b6f291b106a3086d6b75bf)。只读副本已核对该提交；本目录独立运行，无安装、数据库、来源请求、模型调用或上游系统启动。运行结果与选型含义见 [REUSE.md](../REUSE.md)。

从仓库根目录执行，实测 Node **v26.12.1**，使用原生 TypeScript 去类型与 `node:test`，无第三方依赖：

```sh
TZ=UTC node --test docs/design/rebirth-reading/experiments/tests/*.test.ts
TZ=Asia/Shanghai node --test docs/design/rebirth-reading/experiments/tests/*.test.ts
```

两种时区均 **30/30 通过**：保留上游日期测试 20 项，新增日期场景 5 项，发布边界场景 5 项。部分上游测试还在进程内切换纽约／柏林时区。此数目只描述本目录，不表示上游整套回归、来源采集或中文阅读质量已通过。未安装依赖，未运行 TypeScript 项目级类型检查；更低 Node 版本兼容性未测。

## 来源与最小改动

所有引入的 AIHOT 代码和测试适用 [MIT 许可证](vendor/aihot/LICENSE)，保留原版权声明；[provenance.json](vendor/aihot/provenance.json)记录仓库、提交和原文件 SHA-256。上游测试保留在本目录 `tests/upstream-*.test.ts`，同样适用该许可证。

| 本地文件 | 上游文件与改动 |
| --- | --- |
| [vendor/aihot/dates.ts](vendor/aihot/dates.ts) | `packages/backend/src/sources/dates.ts`：日期算法不改；格式化函数改用相对路径；移除 `SourceRow` 类型依赖，只保留函数实际读取的两个配置字段类型 |
| [vendor/aihot/time.ts](vendor/aihot/time.ts) | `packages/contracts/src/time.ts` 第 1–15 行，原样保留 `OFFSET_MS`、`beijingDate`、`beijingTime`；未带入周／月报等其余函数 |
| [tests/upstream-dates.test.ts](tests/upstream-dates.test.ts) | `tests/source-dates.standalone.test.ts`：保留 18 项纯日期测试及原断言，只改 import；移除 2 项 HTML 提取测试、1 项归组文本测试及相应 imports，它们分别依赖 `content/extract`、`events/relate`，本次没有执行 |
| [tests/upstream-published-formats.test.ts](tests/upstream-published-formats.test.ts) | `tests/source-published-formats.standalone.test.ts`：保留全部 2 项测试及原断言，只改 import |
| [vendor/aihot/selected-gate.ts](vendor/aihot/selected-gate.ts) | `packages/backend/src/publication/publish.ts` 第 298–299 行的 selected 表达式原样置于纯函数中；参数类型与包装函数为本试验新增。**未提取整个发布函数** |

## 实际证明与暴露的限制

[跨领域日期样例](tests/cross-domain-dates.test.ts)使用人为构造的文化、交通、科研日期元素，验证中文年月日、真实零点与仅日期的精度区分、跨午夜相对时间、来源时区覆盖及未知日期保留。它们不是已抓取页面，也不是这些来源的可用性证据。

试验保留一个明确限制：`readPublicationDate("讲座将于2026年11月5日举行")` 和 `readPublicationDate("更新于2026年11月4日")` 都能提取日期。该工具负责解析，**不能判定原发时间语义**；调用者必须选对原发元素并区分更新时间／事件时间。中文数字日期 `二〇二六年十一月四日` 返回未知。真实页面元素定位、动态时区／夏令时配置、未来日期可信度及完整采集链未测。

[publication-boundary.ts](publication-boundary.ts)是新写的纯策略适配，输入中的 `selectionCandidate` 假定上游材料、来源及中文卡片资格已经成立；另增独立阅读就绪与去重状态，不拿 `grouping_status=complete` 冒充处理完成。相同 pending 文章在原 selected 谓词下为 false，在独立阅读及去重已完成时可入选；pending 关系仍不输出为事件依据。还检查撤回、完成两项关联后撤销其一、普通报道原有门槛。新字段目前只是内存契约，没有落入 AIHOT 的表、事务、同步账本或通知流程。

这些测试证明“日期工具可携带原回归独立运行”和“一处发布策略可以表达目标差异”。**尚未证明整站 fork 只改这一处就足够**。事件卡与热点的身份、服务端偏好、类型分页、数据库并发、撤回传播与上游发布出口均未在 AIHOT 中集成验证。
