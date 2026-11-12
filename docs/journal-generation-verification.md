# 监理日记生成调整验收记录

日期：2026-11-12。项目：公路工程业务智能体层。

## 1、交付范围与状态

已实现用户批准的识别、生成两阶段：recognize 输出 data 可以直接提交给 process；journal 内部顺序执行相同两阶段。两个生成入口输出规定的 code/message/data/jsonData，包含原文 content、施工内容、巡视四项和旁站五项。

MainWorkAgent 更名为 JournalAgent，旧工作拆分模块与关键词/规则提取代码已删除。生成字段无依据时为 null，普通栏目不进入模型，工作原文回显不计入生成字段的事实检查。

代码与离线验收已通过；**原始真实照片的端到端业务验收尚未通过**，不能将此记录解释为生产可用性或不存在生成遗漏的保证。

## 2、离线验证

| 命令/范围 | 结果 |
| --- | --- |
| uv sync --locked --group dev --extra ocr-cpu | 通过，未新增依赖 |
| uv run --locked ruff check app tests scripts | 通过 |
| uv run --locked pyright | 0 errors、0 warnings |
| uv run --locked python -m scripts.docs.check_openapi | 正式监理日记子契约与完整草案一致性检查通过 |
| uv run --locked pytest -v --cov=app --cov-fail-under=85 | 451 passed、3 skipped；覆盖率 94.43% |
| 最终提示词修改后的 Agent/API 相关回归 | 22 passed |
| git diff --check | 通过 |
| 本次涉及的全部 24 个 Python 文件格式检查 | 通过 |
| uv run --locked ruff format --check app tests scripts | 未通过：既有 alignment.py 两条注释前空白不符合格式；HEAD 中已存在，本次未修改该文件 |

3 个跳过项为平台相关 CUDA 测试，未通过跳过新增或弱化本次用例。独立代码审查发现列表序号误当业务数字的问题，已先复现失败再修复；真实模型验证另发现桩号后缀“处”误当工程量，也已补回归并修复。

## 3、真实依赖与内容验证

模型为 qwen3.5:9b-q4_K_M；JOURNAL_TIMEOUT_SECONDS=30、JOURNAL_CONCURRENCY=1，保留现有显式配置的模型回退。LangChain 1.4.6、langchain-core 1.6.12、langchain-openai 1.7.2。

- 项目 scripts.common.verify_agents：对临时 API 执行 62 次业务调用，通过。它主要覆盖既有智能体，不代替监理日记内容验收。
- 5 条人工文本开发验收：覆盖稀疏施工与未旁站、巡视问题与未复查、旁站时间/检测数据、带序号纯标题、检测不达要求且未完成复检。首轮 4/5 通过，失败已用于修复校验及改进提示词；复验经允许的空白归一和人工核对为 5/5。它们已参与开发，不作为独立留出集，也不是 5 张真实照片。
- 既有真实照片 jl1.jpg：真实 OCR 返回 200；原始 OCR data 调用 process 和组合入口均返回受控 502。观察到 OCR 桩号、标题和正文存在误识别，生成又出现改写桩号或遗漏时间/记录，关键数据检查阻止了成功输出。原始图片链路未通过。
- 对照照片人工校对工作原文后，保留其他 OCR 栏目，使用最终提示词通过实际 FastAPI process 入口和真实模型复验：200，13.16 秒。核对工作原文回显、施工范围、旁站起止时间、检测点数/数值/单位、巡视观察记录。该结果只证明这 1 条校对文本可处理，不代表原始图片端到端成功。
- 最终提示词再次处理原始 OCR data：502，14.22 秒；保留失败记录，没有放宽事实校验制造成功。

首轮、复验、模型拒绝原因及输出保存在 Git 忽略的 verification/ocr/；全套测试输出为 verification/journal-generation-pytest.txt。真实业务输入与响应不提交。

## 4、部署与残余限制

8310、8311 临时验收服务均已关闭。8309 由其他方式启动，项目重启脚本按规则保留该进程；未将现有部署宣称为已更新。

调用方需要将 recognize.data 直接作为 process 请求，读取 data.jsonData，并更新 patrol/witness 的嵌套类型。配置键改为 JOURNAL_TIMEOUT_SECONDS、JOURNAL_CONCURRENCY，旧 MAIN_WORK_SPLIT_* 不再生效；已有 .env 保留，部署者需迁移自定义值后重启对应服务。

仍需使用独立标注的真实业务照片/校对文本扩大验收，统计完整事实保真、字段归属、失败率和耗时。机械检查不能证明人物、动作、地点与肯否定的全部关系正确；当前模型对复杂 OCR 原文仍可能遗漏或擅自纠错。Linux/GPU 部署未验证。
