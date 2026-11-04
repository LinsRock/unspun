# 事件材料来源与回放边界

这是截至 2026-11-04 本轮逐条核读与编选的历史回放材料：12 条来源观测、3 个事件、3 个领域。不是实时采集或当前热点；没有平台关注观测，三个事件的 `attention` 均为 `null`。材料范围为 2024-06-04 至 2025-03-11。

所有可读内容均为简短中文转述，原文入口、发布日期、署名及取得范围见 `event-materials.json`。`full-page` 只表示读到该链接的文章正文，不表示阅读了文内链接、图片中全部信息、论文附件或看过视频。`excerpt` 只使用实际取得的摘录；`metadata` 没有内容导读。不是原文全文镜像。

| 材料 | 日期 | 取得范围与来源 |
| --- | --- | --- |
| `material-change6-ascent` | 2024-06-04 | [国家航天局起飞通报](https://www.cnsa.gov.cn/n6758823/n6758838/c10543020/content.html)，正文 |
| `material-change6-return` | 2024-06-25 | [国家航天局返回通报](https://www.cnsa.gov.cn/n6758823/n6758844/n10518102/n10518147/c10565180/content.html)，仅首次取得的正文开头，后续读取超时 |
| `material-change6-repeat` | 2024-06-25 | [新华社报道的国家航天局转载页](https://www.cnsa.gov.cn/n6758823/n6758844/n10518102/n10518157/c10570560/content.html)，正文；重复覆盖同一次返回 |
| `material-change6-basalt` | 2024-11-15 | [地质地球所成果介绍](https://igg.cas.cn/xwzx/yjcg/202411/t20241115_7440526.html)，正文；未读取所链 Nature 论文 |
| `material-shenzhong-open` | 2024-06-30 | [新华社开通报道的生态环境部转载页](https://www.mee.gov.cn/ywdt/szyw/202406/t20240630_1080446.shtml)，正文 |
| `material-shenzhong-first-day` | 2024-07-02 | [深圳交通部门首日车流报道](https://www.sz.gov.cn/cn/xxgk/zfxxgj/bmdt/content/post_11402165.html)，正文；观察时点为 7 月 1 日 |
| `material-shenzhong-unavailable` | 2024-07-03 | [国资委通车报道](https://wap.sasac.gov.cn/n2588025/n2588129/c31099590/content.html)，搜索元数据；打开正文超时，不入选、不作事实依据 |
| `material-shenzhong-month` | 2024-07-30 | [广东省委港澳办转载的满月报道](https://www.gdhmo.gov.cn/xwzx/hzjl/shfz/content/post_75075.html)，仅首次取得的正文开头；标题 25% 的分母未核清，不进入结论 |
| `material-deepseek-release` | 2025-01-20 | [DeepSeek 原始公告](https://deepseek.com/news/deepseek-r1/)，正文；自报性能未独立复测 |
| `material-deepseek-paper` | 2025-01-22 | [技术报告 v1](https://arxiv.org/abs/2501.12948v1)，仅英文摘要与版本历史；未混入 2026 年 v2 |
| `material-deepseek-azure` | 2025-01-29 | [微软接入公告](https://azure.microsoft.com/en-us/blog/deepseek-r1-is-now-available-on-azure-ai-foundry-and-github/)，英文正文；未验证当前服务状态 |
| `material-deepseek-economics` | 2025-03-11 | [彭文生演讲整理](https://lcg.tsinghua.edu.cn/info/1029/1972.htm)，正文；演讲实际发生于 2 月 22 日，观点不当作独立性能审计 |

## 事件文字依据

`events.json` 的 `materialIds` 表示相关材料集合，含重复与未取得正文的来源线索，不代表每一条都是事实依据。进展只引用可支持该进展的材料；未读正文材料从不进入 `developments.materialIds`。

| 事件 | 概况第 1 段 | 概况第 2 段 |
| --- | --- | --- |
| `event-change6` | `material-change6-ascent`、`material-change6-return`、`material-change6-repeat` | `material-change6-basalt`；保留古老岩屑可能来自外部的限制 |
| `event-shenzhong` | `material-shenzhong-open`、`material-shenzhong-first-day` | `material-shenzhong-first-day`、`material-shenzhong-month`；统计口径说明与本轮读取限制属于编辑注 |
| `event-deepseek-r1` | `material-deepseek-release`、`material-deepseek-paper` | `material-deepseek-azure`、`material-deepseek-economics`；明确标明作者观点 |

事件摘要是上述材料的更短概括；`whyRead` 和 `selectionReason` 是编选判断，不冒充来源原话。材料自身两个段落只依据该条 `url` 的实际取得范围。材料分类与文字由本轮逐条核读与编选，没有调用外部付费模型、运行生产采集或使用旧冻结样本。

事件相关且独立入选的文章有 2 篇：样品定年、彭文生署名分析。R1 原始公告作为事件依据保留，避免相同发布消息重复占位。其他材料通过事件详情阅读；重复报道不独立入选，也不刷新进展。全部 URL 为本轮实际搜索并尝试打开的页面，页面可访问性不代表持续采集稳定性。
