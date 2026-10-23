# R2-09 话题偏好后端交接

本批从 `origin/main 0aa1aaa` 建立独立 worktree/venv，实际 Python 导入已核验；先提交 `347ddd5` / `40dcc86` [类型化目标契约](../superpowers/specs/2026-10-23-r2-09-topic-preferences.md)，再实施。后端实现与隔离验证完成后经 PR/CI 交付；当前 PR、合并和关闭部署尚待完成，不预记生产启用。

## 页面接入出口

新开关 `UNSPUN_R2_TOPIC_PREFERENCES_ENABLED` 默认 false，关闭时新 API 经认证后 404；它不会开启混合流、话题发布或处理。旧内容反馈、兴趣与读者接口的请求/响应保持。新接口同样使用 Access 和同源写保护：

| 接口 | 请求与行为 |
| --- | --- |
| `GET /api/topic-preferences` | 原读者快照加 `topic_preferences`；返回共享 version，话题项含 target、followed、feedback、version，不披露失效文本 |
| `PUT/DELETE /api/topic-follows` | `{version, mutation_id, target:{type:"topic", id:UUID}}`；关注/取消关注，不改变反馈 |
| `PUT/DELETE /api/target-feedback` | target 为 `{type:"content", id:整数}` 或 `{type:"topic", id:UUID}`；PUT 附 `value:"interested"或"not_interested"`，DELETE 撤销，不改变关注 |

使用新的 mutation_id 发起新意图；重试同意图保留原 ID、version、目标和载荷。`409 reader_version_conflict` 或 `mutation_id_reused` 的 `detail.current` 带当前完整状态；调用方先展示当前状态再由用户重做。成功重放返回当前状态而非旧结果。无变化操作有持久收据且不增加 version；旧审计记录仍可识别迁移前重放。类型化内容端点复用原内容反馈资源及别名语义，不生成第二份反馈。

新增关注/话题反馈须通过当前 R2-07 公开资格。取消/撤销可针对改名、归档、材料失效或关闭发布的话题；稳定 ID 不跟名称变化。主题词仍是 `kind=term`，不转成订阅。最多 256 个有效话题偏好资源；取消最后一个字段移除当前投影，before/after 历史与请求收据保留。

R2-08 将关注/正反馈的确切话题 ID 加入有界 interest 召回，仍逐项核验发布资格；推荐理由增加 followed、follow_boost、feedback_value、feedback、topic_preference_score。关注 +2、正反馈 +2、负反馈 -3；负反馈暂时抑制关注加分，撤销后恢复。其他话题、内容成员、作者/来源/领域不继承该态度，重要性/公共关注不变。最新仍按原时间规则，偏好/开关变化使旧混合游标 `409 hybrid_changed_restart`；重放和空操作不会凭空失效。未读/点击/滚动均不参与。

## 工程验证与恢复

[同批对照](r2-09/comparison.json)复用 R2-08 已暴露的 12 条真实材料及固定 as_of，追加保留的 R2-07 不可公开 mock 话题和明确命名的控制话题，只调用纯排序函数。10 个偏好状态中，目标位置为无偏好 13、关注 7、正反馈 1、负反馈 14、修改为正 1、撤销反馈 7、取消关注 13；全部撤销回到基线。最新序列、其他候选基础分不变，重要性/公共关注仍缺失。此对照不证明真实话题质量或用户主观效果。

集成测试使用隔离合成材料与 MockTransport，在未放宽的公开校验下覆盖关注/正负/修改/撤销、独立召回边界、同源/同域/成员不传播、多个设备竞争及同请求并发重放、空操作收据、旧内容 API 互通、旧游标、改名/归档/材料/来源/发布关闭及 mock 失效后的撤销。没有任何真实提供方调用。

迁移 `000021` 只新增 `reader_requests`、`topic_preferences`，不回填或改写原数据。[恢复验证](r2-09/recovery.json)：从 `000020` 升级时原 36 张业务表保持；带旧内容反馈/主题词/审计与新话题偏好/空操作收据的完整 pg_dump/restore 后全部表行散列相同，恢复后重放仍有效。downgrade 明确拒绝且数据/schema 不变；恢复使用兼容 `000021` 的镜像或独立完整备份还原，不删除或 stamp 数据。

基线 1,291 项、定向 34 项通过；完整回归 **1,306 项、0 跳过**，Ruff/格式/Pyright 与迁移无漂移检查通过。425 份受保护现存文件保持，旧 40 例排序前后字节一致，前端 115 项及 lint/typecheck、部署/CI 路由 26 项（另 8 subtests）通过。已审查原 Reader 与 `web/src/reader` 调用方、共享资格、召回及迁移：旧端点 DTO 不增字段，旧调用不选新入口；无页面、付费生产者、预算或来源变更。

## 边界与待验

本批生成、embedding、付费重试及提供方查询均 0。预算、paid-stop、未知预留、旧阅读和 R2-04 原件保留；部署前后只读核验及同期旧 R1 自然活动待登记。R2-06 继续暂缓（3/4，真实质量未通过、v6 真实语义未测、整体用户认可 null）；R2-07 真实质量未补记通过。R2-10+ 和清理未开展；本批出口仅是可供页面接入的偏好 API 与排序联动。
