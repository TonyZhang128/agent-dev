# 监理日记工作内容生成语义

状态：`confirmed`。用户于 2026-11-12 批准两阶段串联、完整业务输出、命名优化及删除关键词/规则提取。正式字段以 [journal.openapi.json](../openapi/journal.openapi.json) 为准。

## 1、流程与输入

`/ocr/journal/recognize` 输入图片，返回完整识别结果；将其响应的 `data` 原样提交给 `/ocr/journal/process` 即可生成最终业务日记。`/ocr/journal` 内部顺序执行相同识别和生成阶段，不通过 HTTP 请求自身。

process 校验 fields 完整包含 11 个不同栏目。允许人工校对 text 后重新生成；栏目 text 是处理依据，boxes 原文不覆盖已校对文字。其他栏目映射 common、issues、nextDayPlan，只有 main_work.text 送入 JournalAgent。

## 2、生成与原文

成功包装为 `code=200`、`message=success`、`data.jsonData`。mainWork 包含 content 原文、construction 以及 patrol 四项、witness 五项；两个嵌套对象始终存在，未知子项为 null。main_work.text 为 null 时 content 为 ""；其他 text（含空白和日期）原样映射，不由模型补写。

所有非空白工作原文均调用 Agent，包括带完整标题或纯标题的记录；空白原文直接返回空生成字段。纯标题由 Agent 判断，没有业务内容时允许全部为空，不保留任何标题分类快捷路径。

允许调整语序、合并断句、精简重复及基于已有事实的语言补全，各生成字段通常 1～2 句；不得为篇幅删除关键事实与数据。不能新增部位、日期、人员设备、检测数据、检查/取样动作、合格结论或整改完成状态。没有问题记录不等于未发现问题，要求整改不等于已经完成；不能将施工自动写为已开展巡视或旁站，不将次日计划写成当日工作。

## 3、校验、失败与兼容性

保留严格结构化输出及关键数值、单位、桩号、时间和符号检查。允许合理重复关联数据，不要求数字重复次数或否定词数量相等。原文回显不计入生成字段的事实校验。机械检查不能证明全部语义和事实完整性，仍需独立真实样本验收。

沿用 4000 字符模型输入保护、总预算、并发和显式配置的模型回退。模型不可用、超时、有效输入超限或非法输出保持 502、detail 包装及既有固定文案；请求结构和栏目完整性错误返回 422。图片错误与 OCR 失败仍分别为 400/503。取消信号不吞掉，不返回伪完整结果。

process 不再接受旧 main_work 请求；journal 与 process 同步采用新的完整响应。taskId 和 documentType 仅保留在 recognize 结果，不加入规定的最终业务格式。调用方需同步更新请求对象和成功响应类型。配置更新为 JOURNAL_TIMEOUT_SECONDS 和 JOURNAL_CONCURRENCY，部署必须迁移旧配置键。
