# R1 NYT World 图片说明材料停用 · 2026-10-18

#94 已实际发布为 `594474ca2ef117697838e7e86018f83bae715f6a`。首轮生产中，内容 **8844**（NYT World）进入了 `preview`，实际只有 101 个英文字符的图片说明；卡片只有一条关于催泪瓦斯照片的要点。它不能支持该文章的正文预览能力，原有 G2 通过记录不覆盖这个新反例。

实际 API 于 `2026-10-18T03:20Z` 读取：材料 **1**、抽取器 `r1-material-v3`，只有一段；原文 URL 为 <https://www.nytimes.com/2026/10/17/world/middleeast/israeli-settlers-attack-palestinians-diplomats-west-bank.html>。[精确材料/任务/调用和响应指纹](r1-production-rollout/nyt-caption-suspension.json)保留了这次失败及已发生费用。原始 API 响应仅在私有缓存保留，正文不进 Git。

本 PR 关闭 `nyt-world` 的 discovery/material/paid/publish 四个阶段，付费与发布范围清空。采集 owner 保留 R1、旧来源轮询继续禁用，消费者仍只有一个受控 R1；新华社和其他未合格路径保持关闭。现有 NYT 记录、材料、任务、尝试及已发生费用不删除，关闭 publication 会撤下 8844。首次九路登记保留，只在同一 [production-rollout-v2.json](../evaluations/r1/production-rollout-v2.json) 追加运行停用记录，不能扩大名单。

其余八路继续，WSJ World 的公开有限 RSS 预览仍可作为有限材料验收入口。恢复 NYT World 必须先修正图片说明/正文选材，补新的有界 G2，再通过单独配置 PR；本轮不重调提示、不重做付费评测，也不借局部缺口阻塞合格路径。重启后的自然新增与完整预算/费用核对仍在 R1-15/16/17 中继续，用户验收未记通过。
