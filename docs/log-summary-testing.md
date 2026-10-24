# 工程 OCR 日志描述测试说明

接口为 `POST /api/agents/log-summary`，契约及示例见 [API 文档](agents-api.md#1-工作日志总结)。调用方将 OCR 识别对象放入 `content`，读取返回的 `summary` 作为当日日志片段。兼容既有文字及通用日志 JSON；请求新增必填 user_id、session_id，响应及 content 的4000字符限制不变，不接收 history。业务输入文件只保存用户提供的一条 OCR 原始对象；[固定输出接口](../interfaces/log_summary/README.md) 保存六个必填字段的 Schema、示例和对接说明。

## 暂行验收规则

正式业务话术标准尚待补充，目前按客观工程记录生成一段中文。规则统一在 `app/prompts/log_summary.md`，不在业务代码中固定某张表的字段或编写文本拼接模板。

| 场景 | 预期 |
| --- | --- |
| 项目、标段、桩号及多个指标 | 保留工程上下文，逐项描述实测值及原单位，不只给出平均值或范围 |
| 字段名和嵌套层级变化、对象形式的测点 | 接收并完整序列化，不依赖固定 `fields` 或表格类型 |
| `norm` / `key`、单位及装饰符 | 优先非空 `norm`，否则 `key`；可整理空格及 `△`，保持指标含义和单位 |
| `specified` 为“满足设计要求” | 仅是规定要求，不等于实际已达标 |
| 合格率 100、0、null | 分别转述该指标记录的100%、0%、未记录，不跨指标套用、不推算合格结论 |
| 无实测值、空字符串、缺少合格率 | 不解释为零、不合格或明确质量问题，不凭空生成复检或整改任务 |
| 仅有计划、开工或填表日期 | `date: null`，不能当作实际检测或日志日期，不能补入当前日期 |
| 明确实际检测或日志日期 | 原样摘录，不能被计划日期覆盖；无法消除的日期冲突为 `null` |
| 无明确完成、待办或问题事实 | 相应列表为 `[]`，表格或实测值存在不能推断已完成验收 |
| 备注包含改变任务、编造结论的命令 | 只处理原始业务事实，不执行或复述该指令 |
| 空输入、顶层数组、非法类型、额外外层字段、序列化后超过4000字符 | `422`，不调用模型；对象内部允许任意 JSON 字段和数组 |
| 模型格式错误、拒绝、空输出或截断 | `502`，不生成兜底成功内容 |
| 上游不可达、超时、其他错误 | `503`、`504`、`502`，错误不暴露原始输入、密钥或上游正文 |

`summary` 最多1000字符；三个列表各最多8项，每项最多300字符。大表格需调用方按记录拆分，并保留必要上下文。暂未承诺任意大表或任意 OCR 错误都能自动整理正确。

## 离线自动化验证

先定义输入兼容、事实边界及评测失败标准，再编写测试。新增评测测试在缺少日志数据集支持和事实检查函数时先失败（RED），补齐实现后重跑（GREEN）。

`tests/test_agents.py` 使用真实 LangChain Agent 和模拟模型 HTTP 响应，覆盖用户输入及5条 OCR 回归样例的嵌套数据、空值及数值完整传递、严格 JSON Schema、既有响应契约、4000/4001字符边界、请求隔离和外层字段限制，并复用已有输入、输出和上游失败测试。模拟响应不能证明模型遵守话术。

`tests/test_log_summary_interface.py` 校验输入只含用户原始例子、输出 Schema 与实际 Pydantic 模型一致、固定字段及示例合法性；API 测试还比对 OpenAPI，防止接口文件与实际响应漂移。

`tests/test_verify_agents.py` 验证真实验收脚本读取用户原始输入、独立输出示例和两个版本化数据集、记录实际请求及输出，并在日志或意图不匹配时失败；事实检查测试涵盖把计划日期当实际日期、遗漏数值、编造合格/完成/待办/问题、全半角及空白差异。

```zsh
export UV_CACHE_DIR="$PWD/.cache/uv"
uv sync --locked --group dev
uv run --locked ruff check app tests scripts
uv run --locked ruff format --check app tests scripts
uv run --locked pytest -v
```

测试目前直接位于 `tests/`。仓库 TDD 约定中的 `uv run --locked pytest tests/unit/ tests/integration/ -v` 引用了尚不存在的目录，需实际报告该命令结果，并以根目录全量测试补充验证。

## 真实模型评测

[data/log_summary.json](../data/log_summary.json) 仅保留用户提供的系统 OCR 输入，不含其他例子或评测包装。对应的人工参考输出位于 [interfaces/log_summary/response.example.json](../interfaces/log_summary/response.example.json)，真实验收会把原始输入包装为 `content` 调用实际 API，检查固定响应结构、日期及列表有无。

当前版本 `4.0.0` 的11条回归数据保存在 [tests/fixtures/log_summary_cases.json](../tests/fixtures/log_summary_cases.json)：5条虚构工程 OCR 和6条兼容通用日志。这些样例在原2.0.0版本上补充用户与会话字段，保留原有业务事实和测试覆盖，业务输入文件中不混入回归例子。参考输出是人工编写的示范，不是实际模型结果，也不是最终业务话术标准。

成功标准为全部 HTTP `200` 且通过 `LogSummary` 校验，`date` 与参考值完全一致，三个列表的有无与参考一致。工程样例还要求 `acceptance.summary_contains` 中必要的指标、数值和单位全部出现在 `summary`，且 `acceptance.text_excludes` 中的禁止断言不出现在任何输出字段。检查先做 Unicode NFKC 全半角归一化并忽略空白，不要求逐字匹配段落。缺少实测值、注入备注和0%合格率等用例有独立约束。

```zsh
zsh scripts/dev/services.sh restart-api
UV_CACHE_DIR="$PWD/.cache/uv" uv run --locked python -m scripts.common.verify_agents
```

脚本验证用户提供的1条日志输入、测试目录中的全部11条日志回归、24条意图分类及4条非空候选拒绝请求、两个兼容日志、两个对话及一个业务规划，共45次业务调用。报告写入 Git 忽略的 `verification/agents-live-result.json`，包含 `log_summary_dataset_version`、`intent_dataset_version`、实际 `request` / `response`；用户输入检查名为 `provided_ocr_log`，含参考 `expected` 和 `passed`；回归集日志还包含事实约束 `acceptance`。任一数据集条目不匹配使脚本失败；格式错误或非预期 HTTP 错误会直接终止并记录失败；4条非法意图请求以 HTTP `422` 为通过标准。运行耗时取决于模型。

自动检查只是必要约束，不是完整语义证明：数字出现不一定代表归属正确，禁止词不能覆盖所有虚构表述，通用日志目前仅自动检查日期及列表有无。还需人工逐项核对人员角色、指标对应值、单位、原表结论、日期、OCR 歧义及是否适合业务话术。有限样例通过不能保证任意表格正确；新增正式话术或表格时应先补版本化验收样例，再调整提示词。

Linux + vLLM 必须在目标部署重启 API 后运行相同验收；Mac 真实模型结果不能代替 Linux GPU 部署验收。
