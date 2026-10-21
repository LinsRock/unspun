# R2-06 零付费审计与协议修复

本批仅修复机械审核协议并补齐零付费审计，真实语义质量继续**未通过**。R2-06保持**2/4**，用户认可**null**。生成、embedding、付费重试均0；付费停止、生产新链关闭、原$0.30池及总预算保持。新盲准备、后台页面、生产启用、R2-07+、清理和R3未实施。

从最新main `a27fb73`建立独立worktree `r2-zero-paid-audit`，使用独立venv且确认源码导入。先读CLAUDE、D-038及前序决策、任务板、v4契约、最新grounding验收及32份原响应/请求重建证据，再执行[本批契约](../superpowers/specs/2026-10-21-r2-06-zero-paid-audit.md)。旧请求体是按冻结源码重建并与数据库request fingerprint匹配，不冒充原本保存的HTTP body。

## 两份账本与逐笔凭证

全部未决ID、原错误/响应、提供方ID、预留、免费查询结果和处置逐笔登记于[账本审计](r2-06-zero-paid/ledger-audit.json)，原截面见[生产](r2-06-zero-paid/production-before.json.gz)和[累计评测](r2-06-zero-paid/evaluation-before.json.gz)。预留不是已发生费用，两份账本不合并，也不从提供方余额差额推算免费。

| 账本 | 已知累计 | 物理账本记录 | 未决及预留 | 处置 |
| --- | --- | --- | --- | --- |
| 生产 | $7.80032630 / 18989条usage（含历史覆盖） | 349 | 10笔，$0.431089 | 全保留；均429且缺费用凭证 |
| 原累计评测 | $0.44635293 / 532条usage | 540 | 8笔，$0.514613 | 原七笔$0.484867及新增$0.029746均保留 |
| 同一R2-06池（评测子集） | $0.07734293 / 139次 | 不重置 | 新hold $0.029746 | 已知+新hold $0.10708893；$0.30上限不变，余量不可自动使用 |

原评测六笔没有提供方ID：两笔ConnectError、一笔ConnectTimeout、三笔RemoteProtocolError；另有一笔403区域错误和一笔新429，均不能推定免费。生产10笔和评测2笔可定位ID各一次GET generation，全部404；一次GET key为200。[认证查询结果](r2-06-zero-paid/provider-receipts-v2.json)无可结算逐笔凭证，因此未调用结算、未改变数据库、未释放任何预留。最初在无凭据API容器遇到13次本地LocalProtocolError，未到达提供方；[首次记录](r2-06-zero-paid/provider-receipts.json)保留，修正为既有持钥worker后无网络重试和持续轮询。未更换提供方路由。

生产429原错误明确为Google AI Studio共享上游池限流，余额不足并非该响应的解释。[物理调用核查](r2-06-zero-paid/backoff-physical-check.json)确认10笔未知之后各任务新增HTTP均0。代码路径是HTTPStatusError后60秒退避，下一次遇到UsageUnknown后每300秒budget_deferred；截面累计1068次无需HTTP的deferred领取。保护避免了原请求重复付费，但没有提供方级冷却、没有捕获Retry-After，也没有有界结束；不能称为完善的429恢复策略。本批仅提出有界恢复条件，不重发原未知或调整生产调度。

## 根因复盘与未解决问题

[32笔逐项分析](r2-06-zero-paid/v4-offline-analysis.json)保留首次schema结果、长度、错指纹、target、状态/问题及原response散列。查询/锚点原件与决定再次逐项阅读，采用原冻结标签和严格依据口径。

| 类别 | 原始证据与归因 | 本批结果 |
| --- | --- | --- |
| 长度限制 | task138/140/141/144共24事实超160字符、1推断超240，最长612/434；31份返回均finish_reason=stop，非token截断 | 原判断11/16、11/15已返回JSON有效的成绩不变；未截断、补写或抬限放行 |
| 指纹复制 | task114 packet指纹88位，task124 materials、task130 contract、task136 references各63位；其余审核schema合法 | 将机械复制从模型输出移除，绑定改由持久请求/响应与租约验证后生成 |
| 引用归属 | 连续quote合法不代表整条主张受支持；旧task76锚点事实冒充query的违规写入保留，v4挑战明确拦截不等于自然复测通过 | ID/owner/voice/scope/可见quote门槛保持，不给任意响应加当前指纹 |
| 关系粒度 | task138把人物履历/观察分析的贡献判成same_event；challenge analysis-as-report的classification子项仍supported，虽然inference拒绝整项 | classification混合身份与贡献的设计问题确认，旧标签不改，最小方案另列 |
| 日期冲突/人名 | task126把anchor的Saturday和feed日期补为精确10月17日/2026；task143忽略10月17日/9月17日冲突，并将Carney写成Harper | 未修复、未重审付费；不能以feed“纠正”原文或称日期审核已测通过 |
| 语义漏拦 | task132 query_facts/3把“暴力冲突归因极左翼”扩大为“抗议归因极左翼”；协议合法的query_support标supported | 真实子审核漏拦1/1继续保留；后续格式阻断不是语义拦截成功 |
| 上游限流 | task146及生产10笔429均缺费用；provider shared pool错误有原响应，404无逐笔费用 | 全额hold及停止保留；账务和协议修复不解决上游容量 |

v4自然关系2/4、严格最终覆盖0/9、自然CAS0、完整自然审核bundle0仍是实际结果。只启动4/17查询，其余13未测；新揭封6查询0/6。挑战的日期完整审核及真实双连接CAS未测。正确控制仅有一次4审核→CAS、$0.0078384，不能当自然完整链成本。新协议未进行真实生成，以上语义结论不因此升级。

## 已修复的机械协议

模型wire schema仅含`checks[{target,status,issues}]`与`issues`。内部envelope保留五项服务端绑定并追加request/response/lease凭证；实际请求采用与传输相同的构造器，数据库记录必须匹配task、attempt、模型、阶段、对象、请求散列和缓存logical key，原响应必须与返回内容相同、提供方ID一致且不跨物理请求重放。HTTP后及CAS前复核当前租约、决定、材料和完整envelope。

同attempt精确缓存可复用；另一个attempt的缓存、错包、伪造/串换receipt、过期晚返回、修改原响应、提供方generation重放继续拒绝。四审核完整target与语义supported门槛、query-only材料隔离、原决定不可删改和topic revision CAS保持。v4旧输出不会在运行时被剥字段转换为v5，旧注册和旧任务不会自动升级。没有数据库迁移或账务参数修改。

[真实响应离线回放测试](../../server/tests/test_member_receipt_replay.py)明确只投影已有16份审核的checks/issues，原断言和问题不变；本地mock使用合成generation ID及隔离账本。即使原来指纹错了，也只有离线机械投影可通过，新真实模型的schema服从度尚未测。该回放不能修改原16份响应、挽救旧决定、写回旧成员或取得语义质量分。工程故障测试另见[物理绑定测试](../../server/tests/test_member_receipts.py)。

## 资源与最小调用方案

160/240字符是历史输出体积约束，没有证据可作跨语言质量门槛；本批保持其失败结果，不按已暴露样本调高到612/434。8..8000 quote、12000可见字符、4+4事实/2推断/2引文、20检查及4096/8192 tokens等依据、边界和未测项详见[资源复核](../superpowers/specs/2026-10-21-r2-06-zero-paid-audit.md#资源限制复核)。原含reasoning的66559完整预留、模型、召回和向量边界保持。

最小提案将身份与贡献拆成结构化轴，以原文span/引用选择代替自由复述事实；人名和时间角色仍须从所属原文核验，unknown/conflict显式保留。沿用现有隔离要求，每个关联候选**1判断+4独立审核=5次生成**，确定独立1次，任一失败立即停止；不加事实改写、纠错或多数表决轮。暖向量复用0调用，冷边界最多25版本，仅是上限而非实测成本。明确的旧classification单值投影及旧召回/精度/严格覆盖分母见[最小方案](../superpowers/specs/2026-10-21-r2-06-zero-paid-audit.md#最小调用方案与旧指标映射提案未付费实现)，不得修改原标签/门槛或以新诊断指标替代旧成绩。提案未实施为新的真实评测契约。

## 验证、保护与交付

新建`unspun_r206_zero_paid_tests_20261021`迁移后基线1078项、0跳过，最终[完整回归1112项、0跳过](r2-06-zero-paid/validation.json)通过，包含18项新增协议故障及16份真实内容离线回放。Ruff/格式/Pyright、schema无漂移、18项部署+11项CI范围测试及40案例旧排序通过；首次格式/类型检查失败保留，未覆盖旧失败日志。[旧冻结核验](r2-06-zero-paid/freeze-verification.json)逐份检查历史冻结Git blob和旧证据，原标签/评分/paid-stop、R2-04 worktree保留。

[原累计评测备份恢复](r2-06-zero-paid/before-recovery.json)在新库核对所有表计数/内容散列及序列，原task76违规写入、task110、原预算政策和全部账务原样保护。生产部署前记录阅读、保留表、新链/阶段、R2-04原观察容器和文件；部署后按相同只读探针复核。测试数据库和worktree本批保留，不实施清理。

[源码及调用方审查](r2-06-zero-paid/review.json)通过，[导入核验](r2-06-zero-paid/import-check.json)和[本批源码散列](r2-06-zero-paid/source-manifest.json)已记录。PR/CI及实际部署证据在完成后追加到此节。任何部署仅交付关闭状态的核心，不授权运行成员链。

## 恢复条件

恢复需要认证逐笔凭证、另行明确授权、审查并冻结纠正后的长度/结构/语义方案及有界请求登记，继续使用原累计池和完整预留；不得重试原未知请求或因结算成功自动恢复。下一次有限新请求探测须至少等待max(提供方Retry-After,15分钟)、每登记窗口最多一次，任何429/未知立即停，无路由切换；此策略目前仅是提案。旧暴露门槛、严格依据及所有挑战通过之前不得准备新盲，生产启用另有独立门禁。完整具体条件见[恢复前提](../superpowers/specs/2026-10-21-r2-06-zero-paid-audit.md#恢复付费的必要条件)。
