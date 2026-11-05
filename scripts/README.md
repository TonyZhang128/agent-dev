# 脚本使用说明

所有脚本可从其他工作目录调用，脚本内部定位仓库根目录。Python 验收以模块方式运行时，先进入仓库根目录。

| 场景 | 入口 | 说明 |
| --- | --- | --- |
| Mac 完整开发安装 | `zsh scripts/dev/setup.sh` | Homebrew/uv、dev 依赖、Ollama 模型、本项目服务及真实验收 |
| Mac 前台 API | `zsh scripts/dev/start-api.sh --reload` | 仅用于 macOS 开发 |
| Mac 前台调试 API | `zsh scripts/dev/start-api.sh --debug` | 前台启动并监听 `127.0.0.1:5678`，供 VS Code Attach |
| Mac 后台调试 API | `zsh scripts/dev/services.sh debug-api` | launchd 启动带 debugpy 的 API，供 VS Code Attach；仅用于开发 |
| Mac 前台 Ollama | `zsh scripts/dev/start-ollama.sh` | 复用本机模型存储 |
| Mac 后台任务 | `zsh scripts/dev/services.sh start\|stop\|status\|restart-api` | launchd；仅管理本项目注册任务 |
| Mac 下载网络检查 | `zsh scripts/dev/check-network.sh [proxy_url]` | Homebrew、PyPI、Ollama 连通性 |
| Mac 真实模型及 GPU | `uv run --locked python -m scripts.dev.verify_live` | 通用推理验收 + 本机 Ollama Q4_K_M/GPU 分配 |
| Linux 业务环境安装 | `bash scripts/prod/setup.sh` | Python 3.12、锁定运行依赖、保留已有 `.env` |
| Linux 前台 API | `bash scripts/prod/start-api.sh` | 不同步依赖，拒绝 reload；允许传入其他 uvicorn 参数 |
| Linux 前台模型服务 | `bash scripts/prod/start-vllm.sh [vLLM 参数]` | NVIDIA 检查、独立 vLLM 环境；不安装驱动或模型 |
| 模型权重下载 | `uv run --locked python -m scripts.models.download_qwen35_gguf [--quant Q4_K_M\|--vision\|--check\|--list]` | 从 ModelScope 下 GGUF 并补齐 config.json、tokenizer，落到 `.cache/models/`，供 vLLM 挂载 |
| OCR 模型下载 | `uv run --locked python -m scripts.models.download_ocr_models [--root <目录>\|--check]` | 下载 PP-OCRv6 Medium + PP-OCRv5 Server 三个 ONNX 到 `.cache/models/ocr/`，校验 sha256，供只读挂载 |
| Linux 完整验收 | `bash scripts/prod/verify.sh` | NVIDIA 信息、运行中 API 的业务验收及完整意图、日志评测集、通用真实推理 |
| 通用业务验收 | `uv run --locked python -m scripts.common.verify_agents` | Mac/Linux；调用运行中的 API，验收完整意图及日志评测集 |
| 通用推理验收 | `uv run --locked python -m scripts.common.verify_live` | Mac/Linux；直调 Agent、ASGI、TCP；不检查硬件 |
| OCR 真实验收 | `uv run --locked python -m scripts.common.verify_ocr --photo <数据池相对路径> --form JB12-4.2.2` | 调运行中 API，检查真实识别、简表、填表与 WBS；报告在 verification/ocr |
| 新版监理日志批量识别 | `uv run --locked python -m scripts.ocr.bench_journal <照片目录或文件>` | 本地批量运行 `app.ocr.journal`，结果写入 `verification/ocr/journal-bench.json` |
| 监理日志栏目可视化 | `uv run --locked python -m scripts.ocr.draw_journal_fields <照片>` | 不调用 OCR，把 FIELD_SPECS 画到校正页和原照片；默认输出 `verification/ocr/journal-fields-*.png` |
| OpenAPI 草案导出 | `uv run --locked python -m scripts.docs.export_openapi` | 从当前应用导出到 `interfaces/drafts/`，拒绝写入正式契约目录 |
| 接口评审文档渲染 | `uv run --locked python -m scripts.docs.render_api_markdown` | 把契约渲染为 `interfaces/API.md`；只读视图，不手工维护 |
| OpenAPI 契约校验 | `uv run --locked python -m scripts.docs.check_openapi` | 比较契约与实现；有正式契约时优先检查正式契约，不写文件 |
| 业务意图目录生成 | `uv run --locked python -m scripts.intent.compile_catalog [--check]` | 从 `app/resources/intent/business_pages.json` 生成枚举；`--check` 用于 CI 漂移检查 |

Linux 完整步骤、配置和后台托管见 [部署说明](../docs/deployment-linux.md)。Mac 步骤见 [项目 README](../README.md#环境与安装)。

`dev/` 使用 zsh，只接受 macOS；`prod/` 使用 Bash，只接受 Linux。Linux API 可以独立运行在没有 GPU 的主机；模型服务和硬件验收需要 NVIDIA。通用 Python 验收不依赖 Homebrew、Ollama 或 `nvidia-smi`。

原有 `scripts/setup.sh`、`services.sh`、`start-api.sh`、`start-ollama.sh`、`check-network.sh` 保留为 Mac 开发兼容入口，不会自动切到生产环境。原有 `python -m scripts.verify_agents` 转到通用验收；`python -m scripts.verify_live` 保留 Mac Ollama/GPU 验收语义。新命令请使用明确的环境目录。

开发安装通过 `uv sync --locked --group dev --extra ocr-cpu` 安装 pytest / pytest-asyncio 与 CPU 版 ONNX Runtime，并使用 `uv run --locked pytest -v` 执行离线单元测试。生产 `--no-dev` 环境不安装这些测试工具。

`scripts/models/download_qwen35_gguf.py` 只做下载与校验，不需要 GPU 或 vLLM：默认取 `unsloth/Qwen3.5-9B-GGUF` 的 `Qwen3.5-9B-Q4_K_M.gguf`，再从 `Qwen/Qwen3.5-9B` 补齐 `config.json` 与 tokenizer，按 ModelScope 文件列表的 sha256 校验后写入 `.cache/models/qwen3.5-9b-q4_k_m/`。GGUF 不能单独作为 vLLM 模型：GGUF 加载器要求 `--model` 指向 `.gguf` 文件，并按 `Path(model).parent` 读取同目录的 `config.json` 与 tokenizer。`--vision` 才下载 mmproj，且放进 `vision/` 子目录；`--check` 离线校验已有目录；中断后保留 `.part`，重跑即续传。下载结果与容器变量的对应见 [Docker 生产部署](../docs/docker.md#2-准备权重)。

`scripts/models/download_ocr_models.py` 复用运行时的 `rapidocr_params()`，保证预下载的模型与实际识别一致；默认写入 `.cache/models/ocr/`，`--root` 可指向部署目录，`--check` 只做离线文件和 sha256 校验。容器部署通过 `OCR_MODEL_DIR` 只读挂载该目录，容器内不再联网下载；完全离线时在有网机器下载后整目录拷贝过去。下载源与运行时相同，均为 ModelScope 上的 RapidOCR 3.x 模型。

`scripts/docs/` 只服务于接口契约：`export_openapi` 从 `app.main:app` 生成待确认草案，默认写入 `interfaces/drafts/fastapi.openapi.json`；`render_api_markdown` 把同一契约渲染为 `interfaces/API.md` 评审文档；`check_openapi` 只比较契约与实现并返回非零状态，不覆盖任何契约。正式契约必须由用户批准后人工提升到 `interfaces/openapi/`，详见 [接口文档](../interfaces/README.md) 和 [AGENTS.md 第四节](../AGENTS.md#四接口契约与-api-first-开发流程)。

`scripts/ocr/` 完整迁入 docsvc 的 16 个脚本，并新增新版监理日志批量脚本 `bench_journal` 和栏目可视化脚本 `draw_journal_fields`；统一从仓库根目录以 `uv run --locked python -m scripts.ocr.<名称>` 调用。模板生成会写入配置的模板目录，应先备份；`demo_jianbiao` 会上传到 Java 服务，仅在显式需要演示数据时运行。各脚本用途、参数与资源要求见 [OCR 文档](../docs/ocr.md#辅助脚本)。

真实验收会调用模型，报告写入忽略提交的 `verification/`。业务验收报告 `agents-live-result.json` 的每条 `checks` 记录包含实际请求体 `request` 和 API 输出 `response`。设置 `BUSINESS_API_URL` 可验证其他地址的 API，模型直调仍读取当前进程及根目录 `.env` 的 `LLM_*` 配置，二者需对应同一部署。Linux 验收使用 `--no-sync --no-dev`，避免安装开发工具或在验收时修改环境。

通用业务验收读取 `data/intent.json` 的版本化评测集，逐条比对 `status`、`page`、`action`，并验证缺少/非法 `current_page`、非法历史和旧 `text` 字段被拒绝为 `422`；任何不匹配都会使验收失败。用例和成功标准见 [意图识别测试说明](../docs/intent-testing.md)。

通用业务验收读取 `data/log_summary.json` 中用户提供的唯一原始 OCR 对象，并使用 `interfaces/log_summary/response.example.json` 校验固定响应的日期及列表有无；该条记录名为 `provided_ocr_log`。另读取 `tests/fixtures/log_summary_cases.json`（版本 `4.0.0`，11条，含5条工程 OCR）做完整回归。检查实际日期、列表事实有无、必要指标/数值/单位及禁止断言；忽略空白和全半角差异，不逐字比较参考段落。任一日志不匹配也会使验收失败。报告包含 `log_summary_dataset_version`，用户输入记录包含 `expected` 和 `passed`，回归日志还包含 `acceptance`。完整验收共62次 HTTP 业务调用：58次成功响应、4次非法请求的预期 `422`；意图数据集版本为 `5.0.0`，包含42条业务意图样例及4条非法请求。业务话术与人工复核边界见 [日志总结测试说明](../docs/log-summary-testing.md)。
