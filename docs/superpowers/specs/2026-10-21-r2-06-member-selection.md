# R2-06 身份/贡献与原文选择契约（v6，实施前冻结）

基线为最新 main `0138014`，独立 worktree `r2-member-selection`、独立 venv 与新库 `unspun_r206_selection_tests_20261021`。承接 D-039 最小方案，本批只有关闭实现和离线工程验证：生成、embedding、付费重试及提供方查询均为0。不改模型、路由、账务价格、66559完整预留、$0.30累计池/$1.50分配或 paid-stop；未知预留不结算、不释放。生产新链关闭，旧任务/契约不转换或重启，原件/阅读数据保持。R2-06仍2/4，真实语义未通过，用户认可null。

## 输出与证据

`r2-member-v6`只接受新结构，不读写旧classification字段作为模型决定：

- `identity`单值：same_occurrence / same_issue / related / none / uncertain；表示与候选话题的身份关系。
- `contribution`单值：report / background / opinion / explanation / reprint / none / uncertain；表示查询自身的实质贡献。提及调查、人物或国家不能把分析变成报道。多贡献无法单值确定须uncertain，不按任一标签命中计分。
- `certainty`：certain / uncertain。未知或不确定轴只投影independent；无效JSON/超限不是独立成功。
- `query_facts`、`anchor_facts`各≤4项，名称沿用但内容仅为原文选择，不再含自由复述text。
- 每项含1..2条citations：服务端原reference_id、原段落Unicode码点起止`start/end`（0基、左闭右开）、严格相等的原文quote。不得自动搜索别的位置修正索引，任何角色/voice/scope错配均拒绝。
- 每项必填subject、action、object、location、attribution和time。前五者各为`status`（known/unknown/conflict）及≤2个`spans`；span指定citation_index及quote内Unicode码点start/end，不生成名字/事实文本。known至少1，unknown为空，conflict必须2个不同span。每个span非空且在所属quote内。
- time同样选择span，并必填`role`（occurrence/report/mentioned/unknown）与`precision`（timestamp/day/month_day/month/year/relative/mixed/unknown）。day须有原文明示的年月日，timestamp还须明确时间/时区；month_day不含年份，relative不做日历转换。unknown精度保持unknown，conflict保留两端；不得补ISO日期、年份、时区或纠错。feed/发现/处理日期只是元数据，不能作为发生时间证据；锚点不能补查询。
- `relation`仅一项结构化推断：reason（same_occurrence/same_issue/context/assessment/explanation/provenance/none）、两端事实索引、time（compatible/conflicting/unknown/not_applicable）。没有自由推断文本。关联必须指向两端；索引不得重复/越界。time不是日期归一化或相等判断，仍须语义审核。

引用严格匹配只证明位置存在，不证明选出的主体、动作、对象、归因范围和角色正确。四审核独立验证完整选择及上下文；例如把“警方将暴力冲突归因极左翼”选成“警方将整场抗议归因极左翼”，即使每个span都存在，仍必须拒绝。查询支持仅给query原文，锚点支持仅给各anchor原文，关系/完整依据不看其他审核结果。支持/不确定/问题的原输出保留，不删去不支持的字段来批准。

## 单值旧投影与门槛

| 条件 | classification投影 |
| --- | --- |
| certain + same_occurrence + report，event话题，reason=same_occurrence，两端至少有known occurrence time且relation.time=compatible，主体/动作/对象有据 | same_event |
| certain + same_issue + report，issue话题，reason=same_issue、范围有据 | same_issue |
| certain + 非none/uncertain身份 + background/opinion/explanation，reason=context/assessment/explanation | background/opinion/explanation |
| certain + 非none/uncertain身份 + reprint，reason=provenance，双方出处有选择且内容关系有据 | reprint |
| none或uncertain轴/确定性，或related+report无明确同一身份 | independent |

确定关联却不满足结构前提时失败关闭；日期冲突/未知不得被certain same_event放行。身份/贡献的实际含义、选择完整性、时间兼容和出处是否真的支持关系必须审核，结构门禁不冒充语义判断。服务端投影属性供旧成员关系/评测使用，不让模型同时输出两个可冲突答案。持久决定保留完整新结构，成员basis用固定轴/理由/决定散列及引用位置的机械说明，不再生成事实复述、不截断原文。

原标签、分组、首次输出、分母不变：召回按预期query-topic对≥90%，关系精度按首次明确关联输出的单值投影≥95%（结构失败不能变成正确independent；可识别关联仍纳入精度分母），严格最终覆盖按完整依据及实际CAS≥80%，不合法写入0，全部原挑战门槛保持。新轴准确率仅诊断。旧v3/v4/v5执行登记拒绝当前契约；本批不建立付费执行登记、不准备新盲。

## 总体资源与失败边界

| 资源 | 冻结界限与依据 |
| --- | --- |
| 判断/每项审核输出 | 沿用4096输出tokens；新增原始content UTF-8及规范JSON各≤65536 bytes。64KiB是单个有界消息内存/账本保护上限，非字符到token换算或语义充分性保证；不是按暴露样本最大值拟合 |
| 引用总量 | 每决定≤8选择记录、≤16引用，累计quote UTF-8≤16384 bytes，重复引用重复计费。16KiB作为总输出64KiB的1/4给原文，其余给结构/角色/检查，防止8×2×8000重复原文膨胀；不承诺可覆盖任意文章 |
| 单引文与输入 | 沿用8..8000字符及每材料12000可见字符前缀、原truncated标识；引用位置≤12000，局部角色位置≤8000。未展示的上下文不能推定不存在；缺决定性上下文须uncertain或拒绝 |
| 审核检查 | 仍≤20checks、每级≤10issues；新complete最多8条选择+4项关系轴/投影+4项整体检查=16；不得删问题凑上限 |
| HTTP与队列 | 成员判断/审核固定单次4096，无8192截断重试；finish_reason=length即失败。每新成员task max_attempts=1，任何调用/结构/审核失败停止，不跨租约重签旧响应、不增加纠错/修复/多数表决轮。预算拒绝也终止该新任务，原hold保留 |
| 调用规模 | 每关联候选最多1判断+query_support/anchor_support/relation/complete_basis共4审核；independent只判断。每查询≤4候选，最多4+16生成。向量精确键、32→12召回、每话题≤2锚点、最多25冷版本及原embedding输入界限保持，均非本批实测成本 |

删除160/240自由复述字段并不提高旧失败成绩；新契约整体资源不足就拒绝，不截断事实/引用/JSON，不补造输出。语义是否足够由后续获授权的真实复测决定。

## 接线、验证与交付计划

沿用v5物理request/response、task/attempt/租约及五指纹绑定，在HTTP后和CAS前重查；只缩成员传输重试边界，R1请求和重试语义不变。不加表/迁移/通用框架。部署前审查确认原initialize-production即使已有有效预算也会GET key；在本批部署前收紧为已有enabled生产预算先执行原check_paid_budget只读校验，成功复用、异常失败，不查询提供方或写账本。首次初始化仍走原凭证查询/初始化流程，本批不执行。现有队列、召回、账本、topic revision CAS及查询来源资格保持。

使用已暴露真实原件登记离线挑战：法国归因范围、人物分析冒充报道、月日/年份/相对日期、原文日期冲突、Carney/Harper、query/anchor借用、旧协议/旧租约重放。原文位置匹配但语义错误的案例须进入审核并验证拒绝传播，mock结果明确不是模型语义成绩。保留v5错包/凭证/晚返回/CAS故障回归，新增单请求/失败终止与资源边界测试。新隔离库完整回归、旧40例排序、冻结Git blob/原件/paid-stop核对，审查受影响调用方。PR、必需CI、合并后核对实际部署源码、关闭状态、阅读数据、账本和R2-04保护；简洁更新任务板和交接。

恢复付费仍需要逐笔真实费用凭证、契约/执行登记审查及另行明确授权；结算不等于恢复。后台、R2-07+、清理、R2-04整窗审阅均不在本批。
