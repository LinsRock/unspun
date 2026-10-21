# R2-06 修复与复测证据索引

结论与分母见[本轮验收](../r2-06-repair-2026-10-21.md)。真实技术未过，预算门禁停止，生产新链关闭，用户认可 null。

- `results-v1.json`、`report-v1.py`：首次关系标签报告及当时只读导出程序，原样保留。其 correct-applied/wrong-write 只比较标签，未覆盖完整 basis 归属；89是跨查询缓存机会之和，不是不同向量数。
- `technical-review-v3.json`：同一个独立留出审阅代理在停止后的只读技术复核，核验引用、全部真实审核/CAS、依据污染、旧行及分母；严格覆盖1/6、不合格写入1/2。
- `results-v2.json`、`compile-final.py`：追加严格依据口径；不改原标签/原报告/首次输出。compile只读取证据，不访问数据库或外部服务；输出使用排他创建，重复执行不得覆盖原件。
- `fee-reconciliation.json`、`audit-v1.py`：独立逐笔SELECT对账；保留原命名问题，其 `blind_unused_materials_opened` 实际表示停止后报告程序加载了盲登记，不能理解为修复前解盲。
- `fee-reconciliation-v2.json`：澄清上述元数据，核对执行前后供应商增量与生产R1零增量、原池和下一完整预留停止原因。
- `regression-first-run.ndjson`、`blind-first-run.ndjson`：独占创建的首轮执行记录；原始物理请求/响应、任务、attempt、判断、向量分别在5个 `.json.gz` 中。没有challenge首轮文件，因为未执行。
- `validation.json`、`execution-log-index.json`、`logs/`：工程验证、首次失败、真实失败/预算停止及原日志。部分入口stdout为空，首次事件和账本仍完整保留。
- `freeze-created.json`、`freeze-after-run.json`：真实付费前后103份源码/配置/登记/测试与历史冻结核验。源码/提示/参数首输出后未修改。
- `before-recovery.json`、`after-recovery.json`：原累计库完整备份在新隔离库恢复；全部旧行、表散列/计数/序列和旧预留保持。
- `preparation-*.json`、`paid-entry-review-proof.json`、`prepay-*`、`postdeploy-*`、`final-*`、`delivery.json`：PR/CI先行、实际部署以及始终关闭的生产核验。工程交付检查通过与真实技术失败分别记录。
- `retained-resources.json`：原件、私有留出/完整备份、worktree、隔离数据库和本地隧道的保留位置；本批不清理。

私有封存材料和全量标签不复制到仓库。修复期间根代理只读封存摘要；冻结和旧回归完成后入口消费，首个费用门禁停止后才为报告读取登记。未执行5条不得记成负例、通过或未来仍未暴露留出。真实转载双端/旧原发背景等缺口继续未测。
