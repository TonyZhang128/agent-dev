# 测试与验收

测试以业务需求和已确认契约为依据。离线测试、真实依赖验证和目标部署验收各自回答不同问题；测试通过不等于业务内容正确或运行中的服务已加载新代码。详细规则见 [AGENTS.md 第六节](../AGENTS.md#6测试契约快照与验收)。

## 1、离线检查

在仓库根目录执行与 CI 对齐的检查，使用 Python 3.12 和开发依赖：

```zsh
export UV_CACHE_DIR="$PWD/.cache/uv"
uv sync --locked --group dev --extra ocr-cpu
uv run --locked ruff check app tests scripts
uv run --locked ruff format --check app tests scripts
uv run --locked pyright
uv run --locked python -m scripts.docs.check_openapi
uv run --locked pytest -v --cov=app --cov-fail-under=85
```

GPU 开发环境使用 `ocr-gpu` 替换 `ocr-cpu`，不能同时启用。生产 `--no-dev` 环境不临时安装测试工具。

Ruff 检查格式、导入及基础规则；pyright 检查整个 `app/`，含 Agent 与 OCR；pytest 覆盖率门槛为 85%。CI 还检查 `scripts/prod/*.sh` 的 Bash 语法，具体入口见 [CI 配置](../.github/workflows/ci.yml)。

测试直接位于 `tests/test_*.py`，数据在 `tests/fixtures/`，没有 `tests/unit/` 或 `tests/integration/`。可先运行相关范围定位问题：

```zsh
uv run --locked pytest tests/test_agents.py -v
uv run --locked pytest -k intent -v
```

离线 Agent 测试使用真实 LangChain Agent，在模型 HTTP 边界模拟响应，不要求 Ollama、联网或云端凭据。检查范围包括输入／输出校验、错误、超时、工具循环、路由、生命周期和请求隔离；首次依赖安装可能需要网络。

## 2、契约与 OpenAPI 快照

- `tests/test_routing.py` 与 `tests/fixtures/api-openapi.json` 比较完整 OpenAPI，包括路径、方法、字段、状态、operationId、tags、summary、标题和版本，并检查唯一注册、独立挂载和应用资源隔离。
- `tests/test_interfaces_contract.py` 与 `scripts.docs.check_openapi` 检查实现与接口文档一致性；存在正式契约时以其为准，否则检查待确认草案。
- Swagger `/docs` 和运行时 `/openapi.json` 是实现投影；导出草案不能替代用户批准契约。

```zsh
uv run --locked python -m scripts.docs.check_openapi
uv run --locked pytest tests/test_routing.py tests/test_interfaces_contract.py -v
```

失败时先审查完整差异：非预期变化修实现，已批准的契约变化按流程同步文档与快照；不批量重录、跳过或弱化断言。草案导出与评审 Markdown 的生成方法见 [接口索引](../interfaces/README.md#8生成与校验)。

包版本位于 `pyproject.toml`，API 标题与版本位于 `app/main.py`，分别维护；不要为了修快照而擅自修改元信息。

## 3、真实依赖与业务验收

涉及提示词、推理协议、模型配置或 Agent 流程时，先重启对应 API。macOS 本项目后台服务使用：

```zsh
zsh scripts/dev/services.sh restart-api
uv run --locked python -m scripts.common.verify_agents
```

`verify_agents` 调用运行中算法服务，检查日志、完整版本化意图评测集和对话。进一步验证 Agent 直调、ASGI、TCP，以及 macOS Ollama／GPU 行为：

```zsh
uv run --locked python -m scripts.common.verify_live
uv run --locked python -m scripts.dev.verify_live
ollama ps
```

通用脚本不检查硬件；Mac 专用入口增加 Ollama／GPU 检查。Linux 使用 `scripts/prod/` 对应入口，生产验收运行方式见 [Linux 部署](deployment-linux.md#4真实验收)。涉及开发部署脚本、Ollama 或 GPU 的变更需增加对应真实环境验证。

可用 `BUSINESS_API_URL` 选择业务验收地址；直调仍读取当前进程与根目录 `.env` 的 `LLM_*`，两者须指向同一目标部署。若默认端口由其他方式启动的进程占用，保留原进程；临时回环端口只能证明该临时服务的结果，不能声称默认部署已更新。

业务内容的预期结果须依据事实独立标注，不能直接采用程序输出；预先确定样本、数据集版本、指标和通过阈值。日志需检查事实、数值、单位及禁止推断，意图需比较状态和页面／动作，详见 [日志验收](log-summary-testing.md)、[意图验收](intent-testing.md)。

## 4、OCR 独立验收

Agent 回归不覆盖照片识别质量。准备 `PROJECTS_ROOT` 内的真实照片，通过运行中算法服务 检查 OCR：

```zsh
uv run --locked python -m scripts.common.verify_ocr --photo <数据池相对路径> --task-id <任务ID>
```

该脚本检查存活、静态诊断和响应业务结构，不能代替逐字段准确性验收。需对独立于调试样本的典型、困难照片，人工比对原图、OCR 文本和业务输出；分别记录字段正确率、失败案例、耗时，以及 mainWork 三类内容的事实与关键数据保真。

CUDA EP 必须在目标 GPU 主机真实初始化并执行识别，`nvidia-smi` 或 `/diagnostics` 成功不证明 OCR 已使用 GPU。模板与图像诊断命令见 [模板维护](journal-template-recognition.md)，mainWork 规则与生成验证见 [专题](journal-mainwork-split.md)。

## 5、报告与完成判定

验收输出位于 Git 忽略的 `verification/`，包括 Agent 业务报告 `agents-live-result.json`、推理检查报告 `live-result.json` 和 OCR 报告目录 `ocr/`。业务报告的 `checks` 可包含实际 `request` 与 `response`，属于真实业务数据，不提交 Git。

交付时说明实际命令、测试范围和结果，真实数据的版本／样本／指标／失败案例，以及目标部署是否更新。环境、权限或样本不足的必要场景标记“未验证”，说明补验条件；历史报告不代表当前版本通过。

通过已有测试后，还应对照需求检查边界、异常、依赖故障、超时取消和并发隔离。纯文档变更核对命令、链接和内容一致性即可，不添加仅匹配源码文字的测试，不需要重启服务或触发真实推理。
