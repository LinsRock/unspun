# R1 最终用户验收结案 · 2026-10-19

用户实际体验正式 R1 后给出的结论为 **“有小问题但可接受”**，并列出六项阅读页问题。六项已通过 [PR #99](https://github.com/LinsRock/unspun/pull/99) 修复、正常合并部署并复核。R1-17 据此结案，主线 **19/19 项完成**；R2/R3 未启动。

正式入口：[发现阅读](https://unspun.farstrand.com/reading)、[我的关注](https://unspun.farstrand.com/interests)、[内容后台](https://unspun.farstrand.com/admin/content)、[费用后台](https://unspun.farstrand.com/admin/costs)。运行版本为 `8dd144bc6cf5775e5dfe881cbdc50472bedb6486`。

## 用户反馈处理

1. 同一卡片的多个“文中称”来自同一篇内容的不同要点。共同归属现在集中标注一次；原文陈述、作者观点、问题背景和媒体简介分别保留，各条要点、限定词、顺序及证据不改。
2. 感兴趣/不感兴趣改为拇指图标，支持选中、再次点击撤销、无障碍名称及 44px 点击区域。
3. 已删除指定的阅读价值技术判断说明。
4. 推荐/最新成功切换静默保存；冲突和失败仍可见。
5. 页面初读采用骨架屏，刷新/分页/反馈/导读处理显示局部进度；同排序更新推荐时保留现有卡片。
6. 已删除顶部右侧“中文阅读 · 原文可溯”。

具体原因、代码边界、真实 API 预览及本地截图见[六项收尾记录](r1-reader-polish-2026-10-18.md)。用户结论针对整改前正式页面；整改后的技术验证与该用户结论分开登记，没有声称用户再次逐项复验。

## 发布与验证

- [PR CI](https://github.com/LinsRock/unspun/actions/runs/39130375899) 与[主线发布](https://github.com/LinsRock/unspun/actions/runs/39130608356) 均成功，实际 `Deploy` 步骤执行成功，不以跳过部署冒充发布。
- 前端 **101 项测试**、lint、类型检查、生产构建与 PWA 离线回归通过；后端没有变更，没有向生产或原评测库运行数据库测试，也没有新增付费评测。
- `2026-10-18T13:19:25Z` 实际服务核对：API 目标版本正确，旧 worker **0**、受控 R1 **1**；唯一发布端口仍为 `127.0.0.1:8080`。web 使用 `8dd144b` 固定镜像，API/R1 复用未改动的 `5586fe8` 固定镜像，见[部署证据](https://github.com/LinsRock/unspun/blob/eb5b19f749c8316174e9cc5f6e838d7bbb0aec85/docs/acceptance/r1-reader-polish/deployment.json)。
- `2026-10-18T13:57:29Z` 正式 HTTPS Chromium 自动化浏览器检查成功：首屏 **20 张真实卡片、40 个反馈图标**、共同归属和指定文案移除正确，390px 无横向溢出、浏览器错误 0、生产写入尝试 0。使用原有效 Access cookie，没有改变认证。首次 15 秒未取到卡片的超时保留，原因未确定；后续没有修改产品或认证即成功，见[完整结果](https://github.com/LinsRock/unspun/blob/eb5b19f749c8316174e9cc5f6e838d7bbb0aec85/docs/acceptance/r1-reader-polish/official-browser.json)与[正式页面截图](https://github.com/LinsRock/unspun/blob/eb5b19f749c8316174e9cc5f6e838d7bbb0aec85/docs/acceptance/r1-reader-polish/official-mobile.png)。

原[生产任务、费用与重启恢复](r1-production-operation-2026-10-18.md)、[原反馈版本与撤销](r1-reader-final-api-2026-10-17.md)继续保留，未重复运行付费生成。此前 `04:03Z` 的任务/费用计数是历史截面，不冒充本次实时总量。此次用户评分文件指纹仍为 `55e835ffa071c2f8e285e5682c47837a1f97505c3fba229b0456e9869fe6e36c`，43 条样本的 86 个人工评分字段继续为空。

## 保留范围

当前八路受控路径及各自频率/切片不变，BBC World 仅视频简介；新华社、NYT 及其他未合格路径仍关闭。来源覆盖、候选入选和算法召回仍按不同分母记录，没有补造值得看比例或遗漏参照。本批未改原 $15/月项目、$1.50 单一评测累计分配和 $13.50 生产分配配置，未结零未知费用或释放预留；正常生产调度仍单独计费。

此次结案不补记真人手机复测、外站播放或全部指定来源接入，也不改变 R0 的逐条评价和持续使用缺口。S1–S6 的适配/诊断完成与实际来源接入继续分开；R2 话题和 R3 精选/首页仅保留后续依赖，未启动。
