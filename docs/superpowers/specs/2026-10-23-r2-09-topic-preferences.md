# R2-09 话题偏好后端冻结契约

基线 `origin/main 0aa1aaa`，独立 `r2-topic-preferences` worktree/venv，实际导入核验通过。先提交本契约再实施。仅交付后端、PR/CI/合并及关闭部署；页面留 R2-10，用户主观效果和生产启用另验。R2-06 暂缓，R2-07 真实质量未测；生成、embedding、付费重试和提供方查询均 0，原预算、paid-stop、未知预留、阅读及 R2-04 原件保持。

## 类型与 API

旧 `/api/interests`、`/api/feedback`（整数 content_id）、`/api/reader-preferences` 的请求和响应保持。新目标为判别联合：`{type: content, id: 正整数}` 或 `{type: topic, id: UUID}`。话题 ID 沿用 Topic 稳定身份，名称、成员或版本不是身份；主题词仍是 ReaderInterest(kind=term)，不迁移或推导订阅。

新增 `GET /api/topic-preferences` 返回共享读者 version、原兴趣/内容反馈和 `topic_preferences`（target、followed、feedback、version），不披露失效话题文本。`PUT/DELETE /api/topic-follows` 接 topic target；`PUT/DELETE /api/target-feedback` 接内容/话题 target，PUT 的 value 为 interested/not_interested。写请求均含 version 与 UUID mutation_id。PUT 覆盖同目标反馈，DELETE 撤销该字段；关注与反馈独立，可同时存在。删除一个字段不删除另一个字段。

`UNSPUN_R2_TOPIC_PREFERENCES_ENABLED=false` 为默认：新 API 经身份认证后 404，混合召回/排序不读取话题偏好。开启此开关不启用混合流、话题发布或处理。复用 Access 身份、同源与 Sec-Fetch-Site 写保护、ReaderState 行锁/CAS、ReaderChange before/after 审计。新端点的成功/冲突响应均给当前完整偏好，旧端点响应保持。

同 mutation_id 同载荷返回当前状态，不执行旧动作；同 ID 异载荷（含操作、目标、value、expected version）409。新增持久请求收据涵盖无变化的成功请求；空操作不增加读者版本，仍占用请求 ID。旧变更历史继续可判定重放，不回填改写历史。新话题关注/反馈的 PUT 须通过当前 R2-07 公开资格；不存在、归档、失效、mock、关闭来源/材料/话题发布均不可新增偏好。DELETE 不要求仍可发布，改名、归档、失效后仍能撤销；幂等重放先于资格/CAS 检查。

## 召回、推荐与快照

R2-08 原有各通道/总量边界和资格保持。已关注或正反馈的话题按稳定 ID 进入 interest 召回候选，仍须当前合格发布；负反馈不排除候选、不传播给成员/作者/来源/领域，取消关注不等于负反馈。领域/词匹配保持原逻辑，话题偏好不写回这些兴趣。

工程暂定配置：直接关注 +2；正/负反馈复用 R1 的 positive_feedback/negative_feedback（当前 +2/-3）。直接负反馈存在时关注加分为 0，但 followed 状态保留，撤销负反馈恢复关注作用。topic ranking 明示 followed、follow_boost、feedback_value、feedback、matched_interests 和合计分；客观重要性/公共关注保持独立且缺失为 null。不改变内容分、资格、既有同作者反馈规则或隐式阅读数据。

最新始终按内容原发/话题有据实质进展，偏好只改变候选召回和理由，不重新排序同批候选。共享 reader version、开关及规则进入 R2-08 快照；成功变更使旧游标 409，空操作/重放不制造版本；关闭开关也使开启状态游标失效。来源、材料、话题依赖变化继续原资格和游标约束。

## 实施与验证顺序

1. 独立迁移库全回归基线、旧 40 例排序及当前冻结文件散列；冻结本契约。
2. 增量迁移仅新增 TopicPreference 与 ReaderRequest，不删除旧数据、反馈/兴趣或历史。downgrade 失败关闭，恢复走兼容镜像或独立完整备份还原，不能 drop/stamp 伪造回退。
3. 实现类型化 API、共享事务/收据/审计及有界排序联动；核对旧调用方和 R2-07 资格。
4. 同批候选依次对照无偏好、关注、正反馈、负反馈、修改、撤销、取消关注；检查推荐分量与最新顺序、目标隔离、相同 ID/多设备竞争、旧游标、改名及失效撤销。使用 R2-08 已暴露 12 个 package 和明确离线 mock 话题；工程夹具不计真实语义或用户认可。
5. 测试迁移前旧行保持、请求/审计备份恢复；定向与完整回归、旧排序/冻结、Ruff/Pyright、调用方与差异审查。按现有 PR/CI/合并部署流程，核验 schema/源码、全部新开关关闭、旧阅读与受控 R1 保持；同期旧 R1 自然活动另计。任务板和一份交接只留简短结果及必要证据。
