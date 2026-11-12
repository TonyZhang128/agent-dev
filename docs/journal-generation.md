# 监理日记两阶段生成

对外语义见 [工作内容生成](../interfaces/journal/main-work-processing.md)，机器契约见 [journal.openapi.json](../interfaces/openapi/journal.openapi.json)。

## 1、职责

| 位置 | 职责 |
| --- | --- |
| app/api/ocr.py | recognize 图片识别、process 业务生成、journal 顺序串联 |
| app/ocr/journal/output.py | 将一次 OCR 的全部框、坐标和完整栏目导出；合并工作原文 |
| app/ocr/journal/generation.py | 映射 OCR 栏目、调用生成、检查关键数据、组装最终业务结果 |
| app/agents/journal.py | JournalAgent，复用 StructuredAgent/runtime、超时与并发 |
| app/prompts/journal.md | 简短分栏生成、事实与数据边界 |
| app/schemas/ocr.py | OCR 输入完整性、嵌套工作字段及完整业务响应 |

两个生成入口复用 generate_journal，原文取 main_work.text，不从检测框覆盖人工校对结果。所有非空白内容交给 Agent，无关键词/规则提取路径。只将工作原文传入模型，普通栏目由业务层透传。

## 2、关键数据检查与限制

比较用于检查的文本副本，统一排版、常见单位断行及等价比较符号，不修改原始输入。检查数值、单位、桩号、正负号、比较符号及时间/百分比范围，允许必要的重复关联数据，不要求计数相等。原文回显不能掩盖生成字段的数据错误。

这些检查无法证明所有动作、肯否定与事实关联正确，也不能替代业务人工核对。无业务事实的纯标题由 Agent 返回空字段；非空白输入全部受 MAX_JOURNAL_CHARACTERS=4000 保护。

模型总预算 JOURNAL_TIMEOUT_SECONDS 包含排队和配置的回退；JOURNAL_CONCURRENCY 控制生成并发。旧配置 MAIN_WORK_SPLIT_* 不再生效，迁移部署配置后重启；本机 .env 不由迁移自动覆盖。

## 3、验证与工具

inspect_journal 只导出真实 OCR 报告、recognition.json 和字段覆盖图，不生成业务结果，不调用语言模型；会删除目录中旧版本遗留 response.json，避免混淆。业务生成使用 API 的 process 或 journal，verify_ocr 验证两个调用方式的格式和栏目一致性，不把结构校验等同内容正确。

```zsh
uv run --locked pytest tests/test_ocr_main_work_generation.py tests/test_agents_journal.py tests/test_ocr_journal_generation.py -v
uv run --locked python -m scripts.docs.check_openapi
uv run --locked pytest -v --cov=app --cov-fail-under=85
```

真实模型与独立业务样本还需逐项核对生成事实、数据和字段归属，并记录样本范围、模型配置及失败案例。未执行的验收明确标记未验证。

本次实际执行的测试、真实模型结果、照片失败与部署状态见 [验收记录](journal-generation-verification.md)。
