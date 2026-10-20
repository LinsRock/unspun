# R2-05 话题、成员与版本底座

**底座实现和隔离验证完成，PR/CI、实际发布及部署后核对待记录。** 范围只有 R2-05；R2-04 继续进行中、两条新增来源关闭，不接手其观察验收或来源启用。R2-06+、其他清理和 R3 未实施。

从最新 `main b5f812c7c66d2dd185d9046e21c2c8c413e1b26f` 建立 `/Users/li.cong/.config/superpowers/worktrees/unspun/r2-topic-foundation`、分支 `feat/r2-topic-foundation` 和独立 venv。实际 `unspun`、models、content、topics 导入本轮 `server/src`，没有改共享 editable、原 worktree 或观察挂载。[最小契约](../superpowers/specs/2026-10-20-r2-05-topic-foundation.md)先落文件，作为 `3724279` 独立提交；本批没有页面改动。

## 数据和版本契约

`000018` 增加五张表：UUID 话题（event/issue）、规范内容多对多成员、幂等变更历史、进展修订、overview/guide 派生草稿。主题词仍是原 `term` 资源，不混用话题 ID。成员记录 report/background/opinion/explanation/reprint、判断版本、依据与逐段原文引用；移除保留 inactive 行、重加产生新 revision。别名按最多 64 跳解析为 R1 根；材料必须属于根，legacy、环路、错材料/段落/quote 和超范围 voice 拒绝。

话题行锁、expected_revision 和唯一 mutation 收据提供 CAS 与幂等；重放返回原收据，不复活已撤销成员，晚返回必须同时匹配话题 revision 和实际派生输入指纹。进展只保存显式录入，保留独立发生/报道时间、精度、引用依据和撤回链；unknown 不用抓取或处理时间补齐。原文片段匹配和类型校验是工程检查，**没有实质进展判断或语义审核结论**。

成员/材料/元数据/根及别名身份/来源发布范围/现有合格 card 审核输入发生变化，实时校验对应成员及引用它的进展。无关成员变化不使未引用它的进展失效；全部 active 成员及最新进展进入派生快照，任何变化保守地使话题派生失效。定义修订也进入快照，旧修订 superseded 后不能靠值改回复活。重复观测、无关来源和配额不刷新版本；长期 session 重新加载当前 ORM 状态。动态来源/材料恢复与历史 revision 的边界见契约。

内部 `mutate_topic`、`read_topic`、`derivation_input`、`validate_version` 不发网络请求、不排任务。派生只可存 draft，引用校验不冒充中文/语义/发布通过；R1 card/guide、独立阅读、反馈、旧 Event 和历史日报不改，不强制重生成卡片，不回填生产话题。

## 回归、迁移和保留数据恢复

新建迁移隔离库 `unspun_r205_tests_20261020`，基线 942 项通过，最终完整后端 **982 项通过、0 跳过**；其中话题 40 项含真实双连接并发创建/写入、同请求重放/异请求冲突、CAS、错误引用、版本修订/撤回/晚返回、材料/身份/来源/审核失效、缓存刷新及事务中断。收费处理复用 FakeClient；Ruff/format、Pyright 无错误，Alembic check 无 schema 漂移。旧排序 40 案例通过，重新生成结果与[原冻结报告](r2-04/legacy-ranking.json)字节相同（`a20e6e…`），新输出保存在本批私有缓存，不复制报告。部署 18 项、CI 范围 11 项及原 subtests 通过。完整记录见[验证](r2-05/validation.json)。

[冻结核验](r2-05/freeze-validation.json)保持 27/27；52 份配置、R2-04 原始证据和 R2 基线文件与开工 main 字节相同。card/guide 契约、原模型、排序、worker、留出和全部空用户评价保留。审查覆盖新差异与 canonical/material/qualification、旧阅读/反馈/队列/账务及部署调用方；补强长期 ORM 缓存后定向重审并完成上述最终回归。

[恢复演练 v2](r2-05/recovery-v2.json)从新建 `unspun_r205_recovery_v2_20261020` 的 `000017` 开始，带 legacy 文章/事件/日报、R1 材料/卡片、反馈/主题词、任务、模拟已知费用与 usage_unknown 预留。升级不改全部旧表散列或序列；新增两成员、进展修订/撤回、成员移除/重加和两版派生后，完整 pg_dump→新建 `unspun_r205_restored_v2_20261020` pg_restore。**全部表计数/散列/序列及内部历史/校验视图一致**，重复 upgrade 成功。downgrade 明确报错，原 schema/旧账务及新业务行保持。初次成功演练[原件](r2-05/recovery.json)保留；v2 对应审查后的最终指纹契约。

[固定镜像兼容](r2-05/fixed-image-compatibility.json)在带完整新历史的恢复库验证：最终本地 server `sha256:79629bff80cc18197516a922ea017015d90ae62e5b6a8e8368ce6151a37a97d3`（Python 3.12、schema `000018`）迁移和当前导入成功；旧 `6f4fe4ff38c0b109f5d4648cddda0d4ae476fb93`（头 `000017`）报无法解析 `000018`、退出 255。两次后所有行和 schema 一致，不 stamp、不降级、不删数据。只承诺已验证的当前 `000018` 镜像；其他旧镜像不推定兼容。回退继续使用退役后的部署文件，认识 `000018` 的固定镜像；确需原 schema 时还原到独立库/卷并核对升级后写入差额，原库和新增数据继续保留。

[生产备份隔离恢复](r2-05/production-restore.json)另从实际生产执行只读 pg_dump，成功得到 84,146,943 字节的完整备份并在新建 `unspun_r205_prod_restore_20261020` 还原；升级前后 **28 张旧表计数/散列一致、5 张新表为空**，113 个合格详情正文及推荐/最新前两页完全一致。生产本身不做恢复或降级。所有本批库、备份、测试镜像、worktree 均保留，不删除数据来制造回退成功。[失败登记](r2-05/failures.json)保留错误夹具、探针身份及首次传输超时，不当作来源或生产成功。

## 生产和后续边界

部署前各自带时间的只读截面：[运行](r2-05/predeploy-runtime.json)、[合格阅读](r2-05/predeploy-reading.json)、[生产账务](r2-05/predeploy-production.json)、[原累计评测](r2-05/predeploy-evaluation.json)、[受保护旧数据](r2-05/predeploy-protected-production.json)、[受控 worker 边界](r2-05/predeploy-boundaries.json)和[原观察环境/文件](r2-05/predeploy-observation.json)。提供方仅免费 GET；原评测七笔未知及 `$0.484867` 预留不改，原生产/评测分配、模型和来源配额保持。原八路自然运行费用与本批测试分开，本批新付费请求/实付 **0 / $0**。

PR、主干 CI、实际 Deploy、schema/五张空表、固定 API/worker 镜像、阅读/任务/费用、legacy worker 退役、观察容器及已有原件保留由部署后证据补录，不在本段预记通过。无公开话题或新任务入口。R2-06 才接 embedding/候选/成员判断及共享队列账务；R2-07 接进展识别、生成/审核和公开资格；R2-08+ 再接混合阅读/关注/页面。本批不启动这些阶段，R2-04 的两项未完成检查保持。
