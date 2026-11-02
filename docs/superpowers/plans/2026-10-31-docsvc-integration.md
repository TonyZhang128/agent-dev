# docsvc 合并实施计划

> **For agentic workers:** 使用 superpowers:executing-plans，逐项实现并记录验证。

**Goal:** 将 docsvc 的 OCR、简表、PDF/Excel 填表、WBS 与所有辅助脚本迁入当前 Python 3.12 应用。

**Architecture:** 保留当前应用工厂、Agent 生命周期和五个既有接口；新增 `app/ocr/` 业务模块、`app/api/ocr.py`、`app/api/wbs.py`，脚本集中在 `scripts/ocr/`。OCR 路径通过 Settings 管理，模板按需读取，模型与缓存按应用隔离。

**Tech Stack:** Python 3.12、uv、FastAPI、Pydantic 2、RapidOCR、ONNX Runtime、PyMuPDF、OpenCV、openpyxl。

**Spec:** 本次用户请求的七项要求及仓库 AGENTS.md；原始代码只读来源 `../docsvc/`。

## 全局约束

- 冲突处保留智能体现有逻辑；既有五个操作的完整 OpenAPI 契约保持不变。
- 不复制虚拟环境、缓存、IDE 设置和第二套应用入口；不删除源项目或工作区独立 `ocr/`。
- Python 固定 `>=3.12,<3.13`；运行依赖统一放入 pyproject.toml dependencies，由 uv 更新锁文件。
- 数据池相对路径需要解析、限制目录穿越；`projects/` 前缀和空 `out` 语义保持。
- 新增成功响应保留 `status: 200, data: ...`；原 `/health` 优先，保留新增 `/health/deps`。
- 外部模板、数据和原始输入不纳入 Git；测试使用临时生成的可复现资料。

## 检查重点

- 模板缺失不得阻止主应用导入或 Agent 工作；使用模板的请求明确报错。
- 两个应用配置不同数据目录时，模板、缓存与 OCR 引擎不能串用。
- 输入/输出目录穿越和符号链接不能越过数据池边界。
- PDF 与 Excel 来自相同字段；合并单元格、印刷栏目与公式顺序需要回归测试。
- 公式非法输入、循环引用与部分失败不能成为未处理异常或伪造成功。

## Task 1：锁定原有行为并增加迁移验收测试

- [x] 运行现有全套测试，记录基线。
- [x] 添加新接口缺失、无模板仍可启动、计算、目录约束、应用隔离的失败测试（RED）。
- [x] 使用临时 PDF/Excel、JSON 模板和模拟 OCR 边界构造测试资料，避免依赖 Java 服务。

## Task 2：迁移运行模块、配置和依赖

- [x] 迁移全部五个核心模块，调整为 app.ocr 命名空间，移除运行时代码对脚本的依赖。
- [x] 增加 Settings 路径配置、按需模板读取与应用资源隔离。
- [x] 添加 OCR/WBS Router 和依赖自检，保留既有系统 Router。
- [x] 使用 uv add 整理运行依赖、同步 uv.lock，验证 Python 3.12 导入和新增测试（GREEN）。

## Task 3：脚本与行为回归

- [x] 迁移全部 16 个脚本，统一 scripts.ocr 命名空间和路径配置。
- [x] 替换网络依赖的原 Excel 测试，覆盖真实文件写入、公式、WBS 和 OCR 错误分支。
- [x] 审查 OpenAPI 增量，仅向快照添加已授权的新路由/Schema；既有部分精确比较。

## Task 4：统一风格、文档和交付验证

- [x] Ruff 修复与格式化仅覆盖新增文件和本次涉及文件。
- [x] 更新 README、API/OCR 文档、脚本说明、环境示例与项目规则。
- [x] 执行 uv sync --locked --group dev、Ruff、全套 pytest、compileall、git diff --check。
- [x] 使用本机已有模板和真实 RapidOCR 做临时输出验收；启动回环端口验证合并服务。
- [x] 独立代码审查；记录实际验证结果和剩余限制，不提交或推送。

## 执行记录

- 采用当前干净 `dev` 分支，按用户要求直接修改当前项目；不新建工作树或切换用户分支。
- 保留原项目只读备份；废弃入口与 requirements 不引入目标项目，避免产生第二套配置。

- 完成：296 个离线测试、44 项 Agent 真实检查、真实 OCR/文件生成和单表 PDF/Excel 一致性验证；详见 `docs/docsvc-integration-2026-10-31.md`。
