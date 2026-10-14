# M3-B · 集中核实与排序对照

状态：40项重要性、40项现在是否值得读已完成；本文件为技术核对与AI建议，不是已冻结的人工结论。

## 已保留的用户判断

- 32项值得读、8项不值得读，全部原样同步。
- 事件2215（熊猫回国）重要性从2修订为1，其余39项沿用原数值。
- 5个最早报道早于30天的事件中，用户对2491、2226、2215选否，对2184、2113选是。年龄不是统一拒绝依据；不能由AI给“否”擅自补过期或低质量原因。
- 元数据规则候选：52篇有效、1篇缺失、0篇异常。这里的“有效”仅表示元数据日期通过规则，不证明原文首次发布时间已核实。

## 三个排序判断（请核对；尚未写入正式期望）

| 模式 / 范围 | 建议更靠前 | 后一个 | 当前候选名次 | 依据与结果 |
| --- | --- | --- | --- | --- |
| newest / 7d | 4897 Singapore Q3 GDP grows 5.4% on sustained AI-driven demand | 3492 Vikki Campion, News Corp columnist and wife of Barnaby Joyce, begins role with NSW One Nation | 1 / 7 | 符合；前者最早有效日期更近；新加坡一篇时间缺失，采用另一篇有效日期，需核实时间口径。 |
| hot / 7d | 4029 腾讯WorkBuddy企业版加速迭代，上线一站式 Agent 可观测平台 | 3509 巴基斯坦一火车脱轨致5人死亡 | 1 / 6 | 符合；WorkBuddy近期两家来源有报道；火车事故两篇均新华社，只算一个媒体活动，不能按文章数冒充两来源。 |
| important / 7d | 4612 AI edges closer to solving the Riemann hypothesis, one of math’s hardest problems | 138 新兴经济体拥抱太阳能，发展速度远超欧美 | 13 / 2 | 相反；用户重要性4分与2分的差异，建议核实该偏好是否也适用于重要优先；既有综合分目前给相反次序。 |

最新事件和当前热度分别回答时间与活动，不应为了让所有“值得读”的事件靠前而改变其定义。重要优先目前沿用既有综合分，用户评分4分的4612排第13，2分的138排第2；模型重要性也分别为56/80，单改综合分权重不能保证解决该分歧。若用户确认该优先关系，须记录候选失败并在固定集上评测调整方案，不能修改期望让它通过。

## 需要技术核实的例外

### 3125：疑似混聚类，保留原案例

标题为“Self-Preservation in Language Models”，但成员包含：

- [4393 · Self-Preservation in Language Models](https://arxiv.org/abs/2610.12602)（arxiv-ai）
- [4944 · Private, offline and yours: how to search the literature with local AI systems](https://www.nature.com/articles/d41586-026-03227-4)（nature）
- [5310 · Just say no to OpenAI and Anthropic](https://micahflee.com/just-say-no-to-openai-and-anthropic/)（hn-front）
- [5692 · AI Models Can Provably Hide Arbitrary Capabilities](https://arxiv.org/abs/2610.13928)（hn-front）
- [6824 · Physical Intelligence API Beta: Frontier Models for Every Robot](https://www.pi.website/blog/api-beta)（hn-front）
- [6826 · llm-meta-ai 0.2](https://simonwillison.net/2026/Oct/12/llm-meta-ai/)（simon-willison）
- [6848 · llm-gemini 0.35](https://simonwillison.net/2026/Oct/13/llm-gemini/)（simon-willison）

这些标题分别指向模型自我保护、隐藏能力、本地文献检索、服务商评论、机器人API与两个工具插件，单一事件边界缺乏依据。不能把用户对标题给的2分/值得读自动分配到拆出的每篇文章；不能悄悄删成员让排名变好。保留完整快照并标为失败/边界案例，聚类纠正属于C2；正常排名验收需另有边界清晰、冻结后的真实事件，不能把污染输入的热度解释为单一新闻活动。

### 2113：同一系列的两次发布可能混在一起

- [2284 · Introducing WeatherNext 3, our most advanced and accurate global weather AI model](https://deepmind.google/blog/introducing-weathernext-3-our-most-advanced-and-accurate-global-weather-ai-model/)（元数据日期 2026-09-03T15:02:08+00:00）
- [2294 · WeatherNext: AI model achieves breakthrough in forecasting cyclones](https://deepmind.google/blog/weathernext-ai-model-achieves-breakthrough-in-forecasting-cyclones/)（元数据日期 2026-08-06T15:06:15+00:00）

一个标题是模型新版本发布，另一个是气旋预报能力；同属WeatherNext不证明是同一事件。用户仍认为值得读，不能按旧日期直接排除。保留现有3分/是，先核实成员边界与原文日期。

### 聚合入口的出版方和时间

`hn-front`共链接到以下域名：arxiv.org, blog.glyph.im, micahflee.com, newyorker.com, opper.ai, pi.website, reddit.com。采集入口是Hacker News，链接指向的文章可来自不同出版方。工具已支持逐文章出版方覆盖，避免把整个聚合入口当同一媒体；下表仅提供域名建议，不推断独立证据。

采集代码直接读取RSS的published或updated字段。对Hacker News，此时间可能是讨论条目时间，不应自动称为原文首次发布时间；原文时间需要另核实，未核实条目保持待判定。不同域名不证明原创，同站不同论文也不自动是同一个事件。

### 4897：一篇报道没有发布时间

文章6916（Nikkei）时间缺失，文章7161（Al Jazeera）有有效元数据日期。现有候选按后者作为已知最早时间；未知日期不填抓取时刻，也不保证不存在更早报道。

## 领域与出版方建议（可集中审阅，不需重复打分）

| 事件 | 建议领域 | 用户重要性 / 值得读 | 元数据最早日期 | 来源入口 → 原文域名（分组建议） |
| --- | --- | --- | --- | --- |
| 3492 | 政治与公共事务 | 1 / 否 | 2026-10-13 | guardian-world → theguardian.com |
| 3373 | 军事与教育 | 2 / 否 | 2026-10-12 | aljazeera → aljazeera.com |
| 2491 | 文化与影视 | 1 / 否 | 2024-12-03 | zhihu-hot → zhihu.com |
| 2226 | 文化与阅读 | 1 / 否 | 2024-10-01 | nyt-books → nytimes.com |
| 550 | 科学与AI | 3 / 是 | 2026-10-08 | hn-front → reddit.com |
| 4964 | 能源与国际关系 | 3 / 是 | 2026-10-14 | zaobao-china → zaobao.com |
| 2215 | 生态与公共事务 | 1 / 否 | 2025-12-15 | thepaper → thepaper.cn |
| 4407 | 商业与职场 | 3 / 是 | 2026-10-12 | zhihu-hot → zhihu.com |
| 2751 | 体育 | 2 / 是 | 2026-10-11 | aljazeera → aljazeera.com |
| 4393 | AI与软件 | 3 / 是 | 2026-10-12 | 36kr-newsflashes → 36kr.com |
| 1970 | 汽车与产业 | 3 / 是 | 2026-10-10 | dezeen → dezeen.com |
| 1994 | 文化与文学 | 1 / 否 | 2026-09-25 | lrb → lrb.co.uk |
| 4497 | 经济与税务 | 3 / 是 | 2026-10-12 | xinhua → news.cn |
| 381 | 软件与编程 | 2 / 是 | 2026-10-09 | hn-front → blog.glyph.im |
| 4527 | 教育 | 3 / 是 | 2026-10-12 | xinhua → news.cn |
| 3509 | 社会与交通 | 4 / 是 | 2026-10-13 | xinhua → news.cn |
| 2045 | 设计与艺术 | 4 / 是 | 2026-10-10 | dezeen → dezeen.com |
| 1283 | 文化与科技人物 | 3 / 是 | 2026-10-09 | ars-technica → arstechnica.com；hn-front → newyorker.com |
| 3550 | 科技与设计史 | 3 / 是 | 2026-10-13 | sspai → sspai.com |
| 433 | AI与软件 | 3 / 是 | 2026-10-08 | hn-front → opper.ai |
| 4612 | 科学与AI | 4 / 是 | 2026-10-13 | science-news → science.org |
| 4897 | 宏观经济 | 3 / 是 | 2026-10-14 | aljazeera → aljazeera.com；nikkei-asia → asia.nikkei.com |
| 363 | 宏观经济 | 4 / 是 | 2026-10-09 | ft-home → ft.com |
| 168 | 文化与公共事务 | 3 / 是 | 2026-09-30 | dw-en → dw.com |
| 2184 | 半导体与产业 | 4 / 是 | 2026-05-27 | yicai → yicai.com |
| 236 | 健康与行为科学 | 2 / 是 | 2026-10-08 | economist-latest → economist.com |
| 348 | AI与软件 | 3 / 是 | 2026-10-09 | arxiv-ai → arxiv.org |
| 4029 | AI与软件 | 4 / 是 | 2026-10-13 | 36kr-newsflashes → 36kr.com；caixin → caixin.com |
| 2822 | 交通与公共事务 | 3 / 是 | 2026-10-11 | xinhua → news.cn |
| 1195 | AI与基础设施 | 3 / 是 | 2026-09-23 | bbc-zhongwen → bbc.com |
| 2081 | 政治与公共事务 | 2 / 否 | 2026-10-10 | new-yorker → newyorker.com |
| 4713 | 体育与公共事务 | 3 / 是 | 2026-10-09 | zhihu-hot → zhihu.com |
| 610 | 经济与金融 | 2 / 是 | 2026-10-09 | 36kr-newsflashes → 36kr.com |
| 1164 | 医疗与健康 | 1 / 否 | 2026-09-23 | economist-latest → economist.com |
| 833 | 政治与公共事务 | 2 / 是 | 2026-10-05 | economist-latest → economist.com |
| 138 | 能源与经济 | 2 / 是 | 2026-10-07 | dw-en → dw.com |
| 899 | 政治与国际关系 | 2 / 是 | 2026-10-09 | zaobao-china → zaobao.com |
| 2113 | 科学与气象 | 3 / 是 | 2026-08-06 | deepmind-blog → deepmind.google |
| 3125 | AI（成员混杂待核实） | 2 / 是 | 2026-10-12 | arxiv-ai → arxiv.org；hn-front → arxiv.org；hn-front → micahflee.com；hn-front → pi.website；nature → nature.com；simon-willison → simonwillison.net |
| 1457 | 医疗与AI治理 | 3 / 是 | 2026-10-10 | lancet → thelancet.com |

## 原文只读核查结果

抽查8个原文地址，7个可读，Nature因身份重定向未能读取，不补造其日期或内容。还没有完成全部53篇原文核实。[机器可读记录](origin-verification.json)保留了已知差异，原始生产快照和用户评分均不改写。

- arXiv论文4393的v1提交时间是2026-10-08 18:24:02 UTC，采集字段却为10月12日；[原论文提交历史](https://arxiv.org/abs/2610.12602)支持原始日期。日期字段通过格式规则也可能晚于实际公开时间。
- HN链接论文5692是另一组作者的不同研究，其v1时间2026-10-09 17:55:06 UTC，HN条目为10月13日；[另一论文提交历史](https://arxiv.org/abs/2610.13928)确认差异。这也为3125成员并非单一研究提供依据。
- Micah Lee的评论在[作者页面](https://micahflee.com/just-say-no-to-openai-and-anthropic/)标为10月11日，HN条目为10月12日。机器人[API公告](https://www.pi.website/blog/api-beta)标为10月13日，内容是独立发布。
- WeatherNext两篇官方原文日期分别为[9月3日新版本发布](https://blog.google/innovation-and-ai/models-and-research/google-deepmind/introducing-weathernext-3/)与[8月6日气旋成果](https://deepmind.google/blog/weathernext-ai-model-achieves-breakthrough-in-forecasting-cyclones/)，支持保留日期并核实不同事件边界；不支持直接判为同一事件。
- New Yorker的[马斯克纪录片文章](https://www.newyorker.com/culture/the-lede/in-musk-alex-gibney-punctures-elons-self-mythology)标为10月9日，与采集日期同日；只核实日，不把HN的时分秒当成原文准确时刻。

这些差异属于时间来源及成员边界问题，不能靠用户批准一个日期分类就忽略。B1正式时间契约需明确源条目/公告日期与原文首次公开时间，缺失/不确定时保留原值及依据；不能直接覆盖生产字段或伪造已验证标注。该补充不自动开工生产修复或付费重评。

## 后续处理

1. 请先核对上方三组排序判断；主观评分不再重复填写。领域/分组建议可集中确认或指出例外，原文时间与混聚类例外由AI继续核查并保留未确定结论。
2. 人工确认前，`proposed-review.json`只存建议，不填入`annotations.json`的领域、时间核实、出版方、审阅人或排序关系。
3. 未完成门槛时严格命令继续返回不通过。重要优先分歧和混聚类不靠放宽检查、伪造标签或删困难样本解决。
4. 正式B1仍未激活，B2仍按B1交付后推进；时效性筛查属于D，任何补查都不默认新增付费调用。
