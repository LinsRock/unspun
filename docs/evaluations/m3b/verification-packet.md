# M3-B · 集中核实与排序对照

状态：40项重要性、40项现在是否值得读已完成；本文件为技术核对与AI建议，不是已冻结的人工结论。

## 已保留的用户判断

- 32项值得读、8项不值得读，全部原样同步。
- 事件2215（熊猫回国）重要性从2修订为1，其余39项沿用原数值。
- 5个最早报道早于30天的事件中，用户对2491、2226、2215选否，对2184、2113选是。年龄不是统一拒绝依据；不能由AI给“否”擅自补过期或低质量原因。
- 元数据规则候选：52篇有效、1篇缺失、0篇异常。这里的“有效”仅表示元数据日期通过规则，不证明原文首次发布时间已核实。

## 用户排序反馈（已记录，模式口径待确认）

用户明确提出：巴基斯坦火车脱轨致5人死亡（3509）应排在WorkBuddy更新（4029）前，理由是伤亡应获得优先关注。旧的WorkBuddy在前建议已撤回；这不等同于已观测到事故报道活动更多，也不自动推广成“所有有伤亡事件必定高于所有技术事件”。

| 判断 | 候选目前结果 / 7d | 状态 |
| --- | --- | --- |
| 3509 火车事故 → 4029 WorkBuddy | hot：第6 / 第1；important：第21 / 第8 | 两种现有候选均给相反顺序；需要明确偏好应用于哪种排序，再冻结验收条件 |
| 4612 黎曼猜想 ↔ 138 太阳能 | important：第13 / 第2 | 用户接受任意顺序、委托AI决定；不作为强制验收关系，不再因4分/2分自动宣称排序失败 |
| newest：4897 新加坡GDP → 3492 任职报道 | 第1 / 第7 | 时间口径建议，非本次新增人工优先偏好；日期与异常说明保持 |

黎曼猜想/太阳能暂沿用既有综合分，太阳能在前；不人工加排名覆盖、不为满足非强制关系修改评分或提示。

对于伤亡优先，推荐由“重要优先”评价伤亡与公共影响，热度继续衡量报道活动。若用户要求热度也体现公共影响，须修改热度的产品含义、页面说明与评测，不将重要性加成伪装为已观测报道量。已经提出这一项口径澄清；任何选项都不能通过关键词特判或人工抬单个事件来交付。

现有重要性模型给火车事故36分、WorkBuddy60分；综合分39.26/51.27。事故与WorkBuddy的用户重要性均为4分，当前偏好进一步给出同档的优先关系。因此只调来源权重或复用旧综合分不能保证满足该案例；需要可泛化的公共影响规则、固定对照案例及成本验收后再进入正式排名。

完整反馈与两种候选的失败次序见[反馈记录](priority-feedback.json)。这轮新增反馈不改变40项重要性/阅读标签，也不把技术未核实项标成已确认。

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

1. 主观评分和阅读判断不再重复填写；当前只需明确火车事故优先的适用模式（重要优先，或当前热度也要体现公共影响）。黎曼猜想/太阳能不设硬顺序。领域/分组和原文时间及混聚类例外由AI继续核查，保持未确定结论。
2. 人工确认前，`proposed-review.json`只存建议，不填入`annotations.json`的领域、时间核实、出版方、审阅人或排序关系。
3. 未完成门槛时严格命令继续返回不通过。重要优先分歧和混聚类不靠放宽检查、伪造标签或删困难样本解决。
4. 正式B1仍未激活，B2仍按B1交付后推进；时效性筛查属于D，任何补查都不默认新增付费调用。
