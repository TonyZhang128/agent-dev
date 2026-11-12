# mainWork：规则提取与全文生成兜底

状态：用户于2026-11-08明确确认。正式行为见 [mainWork处理语义](../interfaces/journal/main-work-processing.md)。本文替代旧的单元ID分类设计；旧实现与历史决策通过Git历史追溯，不保留兼容执行路径。

## 1、流程

1. 从 `FieldReading` 取得main_work，按既有阅读顺序合并OCR片段为完整文本，保留必要换行。片段与原文不一致时使用完整原文，不能丢字。
2. 空文本或纯标题直接返回三个null，不调用模型。
3. 优先识别“施工情况”（包括“主要施工情况”）、“旁站情况”“巡视情况”关键词。支持标题与正文同框、跨OCR片段的标题、编号标题、乱序和重复类别；去除标题，重复类别正文按原顺序合并。
4. 规则须找到完整可靠的三类分界且没有未覆盖前文，才直接返回。缺少可靠关键词、标题损坏或文本不能完整划分时，调用 `MainWorkAgent`，把合并全文作为一个请求输入。
5. Agent直接生成construction、witness、patrol三个必填可空字段；不返回单元ID、分类计划或unknown标签。
6. 结构与关键数据检查通过后返回既有HTTP成功结构；无法产生合格结果时保持现有502。table未找到仍在OCR前返回已确认400。

缺少某类内容本来允许null；规则不完整不等于该类不存在，由Agent结合全文判断。不能靠整段复制到三字段、强塞施工或编造缺失内容来制造成功。

## 2、生成边界

允许整理表达、合并断句和去标题，保留全部业务事实与关键数据，不摘要、不补充事实。数字、桩号、时间、单位、肯否定和原有检查结论必须依据输入；不能按示例、当前年份或常识纠正疑似OCR数据错误。mainWork之外字段不进入本Agent，也不被它修改。

规则直接提取时尽量保留正文排版；Agent可整理断行和表达。普通短正文不再按3～6字判成不确定标题。正文中只是提到关键词，不应自动成为标题。

## 3、校验及限制

检查数字计数、桩号、计量单位、正负号、比较符号、时间/百分比区间、否定及明显新增完成/合格结论；不将有业务内容的输入接受为全null结果。

标题的编号只在已识别标题范围内排除，不能删除“1、2号墩”中的1。排版空白、常见单位内部断行和时间内部换行统一用于比较；范围连字符不误认为负号。仅比较副本规范化，不改写输入或擅自修正生成值。

这些是机械保护，不能自动证明全部语义、事实完整性或分类准确性。真实验收仍须逐段比对源OCR和输出。模型不可达、超时、格式错误或关键数据检查失败仍明确返回502，不能承诺所有不可辨输入也成功。

保持 `MAX_SPLIT_CHARACTERS=4000` 模型输入保护；规则已能完整提取时不调用模型。`MAIN_WORK_SPLIT_TIMEOUT_SECONDS` 和 `MAIN_WORK_SPLIT_CONCURRENCY` 沿用原Settings配置，超时包括模型排队。Agent复用共享StructuredAgent/runtime，无SDK旁路、无持久历史。主模型故障仍允许显式配置的云端回退，不新增无界重试或循环修复。

## 4、代码职责

| 位置 | 职责 |
| --- | --- |
| `app/ocr/journal/main_work_split.py` | 合并文字、关键词提取、关键数据检查、规则/Agent编排 |
| `app/schemas/ocr.py` | MainWorkRequest全文输入与MainWorkValues三个字段 |
| `app/agents/main_work.py` | MainWorkAgent结构化生成、并发与总预算 |
| `app/prompts/main_work.md` | 事实保留和三类内容生成要求 |
| `app/main.py` / `app/api/ocr.py` | 应用级实例和HTTP调用接入 |

已删除MainWorkUnit/Assignment/SplitPlan/Category、旧标题强继承、逐单元unknown校验及其测试接口，不保留新旧两套执行路径。成功响应字段及类型不变，标题不再保证出现在值中。

## 5、验证

- 单元回归：关键词提取、合框/跨行/编号/乱序/重复、普通短正文、未覆盖前文、模型兜底、数据变更、合法排版、取消与长度边界。
- Agent集成：真实LangChain Agent，在HTTP模型边界模拟；检查完整main_work输入、三字段严格Schema、故障回退、超时、并发隔离及固定502脱敏。
- 真实数据：先重放已保存OCR，再从7张原图调用API。分别报告规则/Agent路径、三字段完整性、关键数据、正文事实及剩余OCR错误。
- TDD与覆盖率不替代真实图片和业务内容验收；不得为提高成功率忽略数据变更。

```zsh
uv run --locked pytest tests/test_ocr_main_work_generation.py tests/test_agents_main_work.py tests/test_ocr_journal.py -v
uv run --locked ruff check app tests scripts
uv run --locked ruff format --check app tests scripts
uv run --locked pyright
uv run --locked python -m scripts.docs.check_openapi
uv run --locked pytest -v --cov=app --cov-fail-under=85
```
