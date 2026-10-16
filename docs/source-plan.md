# Unspun 首批信息源接入计划

更新日期：2026-10-15。下列来源由用户指定，纳入第一阶段的新增或保留接入范围。清单是内容覆盖目标，当前配置、上游路径、本轮探测和生产可用性分别记录。实际启用需完成路径、时效、正文和部署环境验证。

**R0 实测更新：**19 项已完成本轮采集验证，最新栏目、正文、日期、作者、运行依赖与失败见[来源验证报告](research/2026-10-15-r0-source-validation.md)，[43 个真实候选](research/r0-2026-10-15/review-sheet.md)待用户评价。新增路径没有多日稳定性结论；澎湃现用镜像和网易旧榜单存在内容过期，界面目标正文、36氪文章、微博与雪球仍有明确限制。本轮没有修改运行配置或部署。下面保留指定范围及初查入口，不能据初查成功推定最新可用状态。

## 用户指定来源与接入范围

分类沿用用户表达，用于整理来源，不限制该来源的内容只能归入这个领域。多个栏目属于同一发布方；同一报道在多个平台出现时保留传播关系并去重。

| 分类 | 来源 | 首批覆盖目标 | 原始接入状况与验证入口 |
| --- | --- | --- | --- |
| 新闻 | 新华网 | 国内、国际要闻与重要发布 | 已配置 `xinhua`，使用 [news/xhsxw 路径](https://github.com/DIYgod/RSSHub/blob/d24f5136487a388662ec6656e4f1ba4ff46b0ed8/lib/routes/news/xhsxw.ts)；核实该栏目对目标范围的覆盖，再补必要栏目 |
| 新闻 | 联合早报 | 中国与国际两个范围 | 已有中国实时频道；按[上游实时频道](https://github.com/DIYgod/RSSHub/blob/d24f5136487a388662ec6656e4f1ba4ff46b0ed8/lib/routes/zaobao/realtime.ts)补国际频道，分别采集和验收，不能用中国频道代替两者 |
| 新闻 | 南方周末 | 新闻、深度报道与有价值的观点文章 | 未配置；上游有[频道路径](https://github.com/DIYgod/RSSHub/blob/d24f5136487a388662ec6656e4f1ba4ff46b0ed8/lib/routes/infzm/index.ts)和热门路径，先验证新闻及深度内容样本 |
| 新闻 | 澎湃新闻 | 要闻、社会与深度内容 | 已配置第三方镜像精选源；重新验证更新、正文和原始出处，评估原站路径 |
| 新闻 | 人民日报 | 日报重要报道和官方发布 | 未配置；优先验证[人民日报数字报](https://github.com/DIYgod/RSSHub/blob/d24f5136487a388662ec6656e4f1ba4ff46b0ed8/lib/routes/people/paper.ts)，人民网其他栏目作为补充范围另行核实 |
| 新闻 | 新京报 | 要闻、社会与深度报道 | 未配置；上游有[栏目路径](https://github.com/DIYgod/RSSHub/blob/d24f5136487a388662ec6656e4f1ba4ff46b0ed8/lib/routes/bjnews/cat.ts)，需确定栏目及正文能力 |
| 新闻 | 界面新闻 | 新闻、财经商业与相关深度内容 | 未配置；历史记录有海外 VPS 访问失败，本轮不据此永久放弃，重新验证[当前栏目路径](https://github.com/DIYgod/RSSHub/blob/d24f5136487a388662ec6656e4f1ba4ff46b0ed8/lib/routes/jiemian/lists.ts) |
| 新闻 | 网易新闻 | 综合热点，按价值选取社会、财经、科技等内容 | 未配置；上游有[新闻排行榜](https://github.com/DIYgod/RSSHub/blob/d24f5136487a388662ec6656e4f1ba4ff46b0ed8/lib/routes/163/news/rank.ts)和专题路径，验证目标栏目与原始发布方 |
| 新闻 | 腾讯新闻 | 综合热点与有价值的报道 | 未配置；本轮核对到的是[账号文章路径](https://github.com/DIYgod/RSSHub/blob/d24f5136487a388662ec6656e4f1ba4ff46b0ed8/lib/routes/qq/news/user.ts)，综合栏目或热点发现需进一步验证，不能用任意账号替代全站覆盖 |
| 科技 | 36氪 | 科技商业快讯与文章 | 已有快讯；按[上游分类路径](https://github.com/DIYgod/RSSHub/blob/d24f5136487a388662ec6656e4f1ba4ff46b0ed8/lib/routes/36kr/index.ts)将文章单独作为新增范围验证，不能把快讯接入记成已支持完整文章 |
| 知识 | 知乎日报 | 日报精选内容及可得正文 | 未配置；本轮[列表接口](https://daily.zhihu.com/api/4/stories/latest)和一篇详情返回成功，取得正文与原内容入口，继续核实时效与完整度 |
| 知识 | 知乎热榜 | 发现公共话题，再筛选有内容的回答与讨论 | 已有热榜；现有[问题与摘要路径](https://github.com/DIYgod/RSSHub/blob/d24f5136487a388662ec6656e4f1ba4ff46b0ed8/lib/routes/zhihu/hot.ts)不等于回答全文，需补充有阅读价值的材料获取 |
| 知识 | 豆瓣 | 优质书影评论、长文或小组讨论，具体偏好继续收敛 | 未配置；本轮发布方[书评](https://www.douban.com/feed/review/book)和[影评 RSS](https://www.douban.com/feed/review/movie)各返回 20 条，先作为可验证路径；不把片单、榜单当作评论全文 |
| 财经 | 雪球 | 今日或热门讨论，以及有价值的分析文章 | 未配置；上游[今日](https://github.com/DIYgod/RSSHub/blob/d24f5136487a388662ec6656e4f1ba4ff46b0ed8/lib/routes/xueqiu/today.ts)与[热门路径](https://github.com/DIYgod/RSSHub/blob/d24f5136487a388662ec6656e4f1ba4ff46b0ed8/lib/routes/xueqiu/hots.ts)声明浏览器依赖，需要验证运行条件、文本和互动观测 |
| 财经 | 财富中文网 | 财经商业文章，兼顾科技与研究内容 | 未配置；上游有[首页及分类路径](https://github.com/DIYgod/RSSHub/blob/d24f5136487a388662ec6656e4f1ba4ff46b0ed8/lib/routes/fortunechina/index.ts)，需验证文章、时间、作者和正文 |
| 生活 | 微博 | 热搜、公共话题与值得看的帖子，允许补充喜欢的博主 | 未配置；本轮核对的[用户](https://github.com/DIYgod/RSSHub/blob/d24f5136487a388662ec6656e4f1ba4ff46b0ed8/lib/routes/weibo/user.ts)和[关键词路径](https://github.com/DIYgod/RSSHub/blob/d24f5136487a388662ec6656e4f1ba4ff46b0ed8/lib/routes/weibo/keyword.ts)声明浏览器依赖，热搜发现路径仍需单独验证 |
| 国外 | BBC | 国际重要动态，中文报道优先适配 | 已有国际与中文配置；本轮[国际 RSS](https://feeds.bbci.co.uk/news/world/rss.xml)返回成功，后续复验栏目覆盖、翻译与可得正文 |
| 国外 | 纽约时报 | 国际要闻及相关优质报道，兼顾已有中文源 | 已有国际与中文配置；本轮[国际 RSS](https://rss.nytimes.com/services/xml/rss/nyt/World.xml)返回成功，后续复验覆盖和可得正文 |
| 国外 | 华尔街日报 | 国际与财经重要报道 | 已有国际配置；本轮[国际 RSS](https://feeds.content.dowjones.io/public/rss/RSSWorldNews)返回成功，财经范围与可得正文另验 |

这次清单是新增与保留的优先范围，不替代此前的少数派、量子位、三联及 B 站等候选。重要领域缺口仍按覆盖表补齐。国际综合主干按 BBC、纽约时报和华尔街日报收敛，旧配置中的其他英文来源不自动成为新版默认范围；专题一手材料按需要评估。

## 后续探索

| 平台 | 希望支持的方向 | 本轮可行性线索 |
| --- | --- | --- |
| 微信公众号 | 选定公众号更新及文章阅读 | 上游存在[公众号主页](https://github.com/DIYgod/RSSHub/blob/d24f5136487a388662ec6656e4f1ba4ff46b0ed8/lib/routes/wechat/mp.ts)、[搜狗](https://github.com/DIYgod/RSSHub/blob/d24f5136487a388662ec6656e4f1ba4ff46b0ed8/lib/routes/wechat/sogou.ts)等路径；特定主页列表不等于任意公众号稳定同步，后续验证覆盖与更新能力 |
| 小红书 | 选定作者、专题或有价值的笔记 | 上游存在[用户](https://github.com/DIYgod/RSSHub/blob/d24f5136487a388662ec6656e4f1ba4ff46b0ed8/lib/routes/xiaohongshu/user.ts)和[专辑路径](https://github.com/DIYgod/RSSHub/blob/d24f5136487a388662ec6656e4f1ba4ff46b0ed8/lib/routes/xiaohongshu/board.ts)，声明浏览器依赖，用户路径有可选 Cookie 配置；公开范围、内容获取与稳定性后续验证 |

两者保持后续探索优先级，不因发现上游路由就记成已经支持或纳入第一阶段的上线承诺。

## 本轮证据与引用

本轮公开端点探测在当前执行环境进行，没有通过生产部署环境复验。BBC、纽约时报、华尔街日报核对的是 RSS 条目；知乎日报核对列表和一个详情；豆瓣核对书评、影评 RSS。一次成功返回不代表持续更新或正文完整，观测保存在[探测记录](research/2026-10-15-requested-source-checks.json)。此前来源初查见[初查记录](research/2026-10-15-source-feasibility.md)。

RSSHub 路径依据本轮上游源码快照核对，提交参考为 `d24f5136487a388662ec6656e4f1ba4ff46b0ed8`；不是项目当前运行镜像的能力承诺。各路径依据已在对应来源行链接，探测记录保存源码指纹和声明的运行依赖。

## 接入执行要求

每个来源固定栏目或内容范围、候选 URL、作者和发布时间依据、正文完整度、是否需浏览器或凭证、更新周期与失败退避。新增路径先在目标环境验证，再修改实际配置；明确失败的来源保留原因和待解决项，不静默移出用户指定名单。

优先补齐早报国际和 36氪文章，并验证已有原生订阅及知乎日报、豆瓣书影评论等低依赖路径。浏览器依赖来源另做运行验证，期间并行推进其他来源。源站原文、平台摘要、榜单观测与 AI 整理分别保存，平台上的转载按实际发布方和原始出处处理。

## R1 实施增量（2026-10-16）

R1-05/08 已实现 9 条标准路径的元数据/材料契约及默认关闭的阶段配置，见[实施与单次探针证据](acceptance/r1-ingestion-materials-2026-10-16.md)。这不增加正式发布名单，也不把一次本机成功记成来源稳定。目标观察按[标准 v1](evaluations/r1/source-observation-v1.json)逐路径开展；日报/数字报、新中文栏目和专项路径继续保留各自验收，不静默删去。旧生产 AI worker 保持停用。
