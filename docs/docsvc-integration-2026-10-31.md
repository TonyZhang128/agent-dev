# docsvc 合并验收记录

日期：2026-10-31。项目：`qwen-business-dev`；来源：相邻 `docsvc` 工作副本。以下结果针对本次工作区代码，不代表已发布或已更新其他正在运行的部署。

## 迁移范围

| 来源 | 合并位置与处理 |
| --- | --- |
| `app/core/{form_ocr,grid,jianbiao,wbs_draft,deps}.py` | 全部迁入 `app/ocr/`；资源、字段规则和请求模型独立组织 |
| `app/routers/ocr.py`、`wbs.py` | 迁入 `app/api/ocr.py`、`wbs.py`，由现有聚合 Router 注册 |
| 原 health/main/run | 保留智能体现有主入口及 `/health`；仅增加 `/health/deps`，不引入第二个应用 |
| `scripts/*.py` | 16 个功能脚本及包入口完整迁入 `scripts/ocr/`，检查报告与打包输出迁到 `verification/ocr/` |
| 原 Excel 测试 | 用可复现的临时模板/PDF/Excel 夹具替代 Java 网络取配置，保留合并单元格和印刷栏目回归 |
| requirements | 所需运行依赖合入 pyproject.toml dependencies，由 uv 更新 uv.lock；重复 Web 依赖不重复声明 |
| 模板、业务文件、虚拟环境、IDE 配置 | 不复制；源目录和已有独立 `ocr/` 保留。根 `.env` 只追加缺失的 4 项 OCR 路径，已有值不覆盖 |

不引入无调用代码的 multipart 服务端解析、统计学习预留包或训练环境；Pillow 被脚本直接使用，作为直接依赖声明。原智能体固定依赖版本不变，Python 为 3.12.13，项目约束保持 `>=3.12,<3.13`。

## 验证结果

| 检查 | 实际结果 |
| --- | --- |
| 合并前 pytest 基线 | 251 passed |
| 合并后全套 `uv run --locked pytest -v` | 296 passed，新增 45 个用例 |
| `uv sync --locked --group dev` | 75 个包解析成功，环境已同步 |
| Ruff lint / format | 全部通过 |
| Python compileall | app、scripts、tests 全部通过 |
| 旧 OpenAPI 契约 | 原 5 个操作、全部旧 Schema、标题/版本逐项精确一致，仅新增 7 个操作及 4 个请求 Schema |
| 原智能体真实 HTTP 验收 | 本机已有 Ollama/Qwen，44 项检查全部通过，覆盖日志、完整意图集、聊天和历史 |
| OCR/WBS 真实 HTTP 验收 | 临时回环 API 的依赖、表样字段、PNG、普通 OCR、简表、重算、WBS 均完成 |
| 真实简表照片 | 识别 19 个字段，定位为 contour+table |
| 真实完整表样图 | 识别 52 个文本框、7 个字段，anchors 对齐成功 |
| PDF/Excel 实际生成 | 在项目 verification 下实际生成并打开文件；原数据池只读 |
| JB12-4.2.2 逐格一致性 | 1 张通过，0 个问题，无 PDF/Excel 缺值、撞格、倒序或覆盖印刷文字 |
| 迁移完整性与审查 | 独立核对原脚本无遗漏；发现的 5 个重要问题均复现、修复并由回归测试验证 |

关键改进包括：模板延迟读取；OCR 引擎、模板/几何缓存按应用隔离并在停止时释放；Excel skipped 随本次结果返回；输入输出及 WBS 子文件符号链接限制；非法嵌套配置返回校验错误；Mac/Linux 造样图字体适配。

实际验收记录在 Git 忽略的 `verification/agents-live-result.json`、`verification/ocr/`，不提交照片、业务输入或原始模型结果。临时 18309/18310 API 均已关闭；未修改 launchd 注册、未替换其他服务，也未提交或推送 Git。

## 验证范围与限制

- 测试有 5 条来自 PyMuPDF/SWIG 的上游弃用警告，没有项目测试失败，未通过屏蔽警告制造通过。
- 简表照片用普通目标表接口识别时返回 mismatch 警告；对应简表流程成功。完整目标表图则成功对齐，不能由此推断任意照片的识别准确率。
- Linux/GPU、CUDA OCR、Java 上传演示和其他全部表种未在本机逐一验收；WBS、多页及识别准确率边界见 [OCR 文档](ocr.md)。
- 本次选择直接修改现有干净 dev 分支，并保留源项目作为备份；没有引入第二工作树、另一套运行环境或重复启动入口。

在项目根目录启动：`uv run --locked uvicorn app.main:app --host 127.0.0.1 --port 8309`，或使用现有 VS Code `Debug API (launch)`。资源配置与脚本参数见 [OCR 文档](ocr.md)。
