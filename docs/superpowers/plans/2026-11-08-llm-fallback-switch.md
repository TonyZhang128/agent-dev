# LLM 回退环境开关实施计划

> 执行方式：在当前开发分支完成测试驱动实现与验收，保留已有 OCR 修改。

**目标：** 开发和生产都能保留云端密钥，通过环境变量单独关闭或开启既有 LLM 回退。

**设计：** 在 `Settings` 增加 `llm_fallback_enabled: bool = False`，对应
`LLM_FALLBACK_ENABLED`。`ModelService.fallback_enabled` 同时检查开关和非空密钥；
既有 runtime 使用这个结果注册回退中间件，总超时也使用相同判断。

**范围：** 更新开发、Linux、Docker 配置示例及 Compose 注入、README 和部署说明。
不修改 HTTP 契约、提供方适配、现有回退异常范围或用户实际 `.env`。
默认关闭是本次实现选择；旧部署若只配置密钥，需要补 `LLM_FALLBACK_ENABLED=true`。
开启但密钥为空时仍按原有逻辑关闭回退，不新增启动失败。

**验收：** 默认或显式关闭时本地失败只请求本地、返回既有错误且不增加超时；
开启且有密钥时本地失败才调用云端；本地成功不调用云端；空白密钥不启用；
环境变量覆盖 `.env`；开发和生产模板可加载；Docker 正确注入开关。

- [x] 先增加运行时开关、配置优先级和 API 行为用例，观察预期失败。
- [x] 最小修改 `app/config.py`、`app/llm.py`，同步示例及文档，复跑相关测试。
- [x] 执行 Ruff、Pyright、契约校验、完整 pytest 和差异审查。
- [x] 检查本项目服务并尝试真实验收，分别记录本地、云端和生产环境未验证项。

**验证命令：** 使用 `UV_CACHE_DIR="$PWD/.cache/uv"`，先执行
`uv sync --locked --group dev --extra ocr-cpu`，再执行项目规定的完整检查。
真实验收使用 `scripts/dev/services.sh restart-api` 和 `scripts.common.verify_agents`；
其他进程占用端口时保留该进程，用临时回环端口验证。

**基线：** `tests/test_runtime.py` 与 `tests/test_agents_main_work.py` 共 22 项通过；
已有 PyMuPDF/SWIG 弃用警告。工作区已有 `app/ocr/journal/alignment.py` 修改。

## 验证记录

- RED：6 项失败，原因均为现有逻辑忽略开关而仍访问云端或增加超时预算。
- GREEN：相关用例 33 项通过。已有回退用例仅补显式开关，保留原业务断言。
  新增 API 用例错误文案由草拟的“模型服务暂时不可用”校正为既有契约的
  “模型服务不可达，请检查 Ollama/vLLM”，不修改生产错误响应。
- 全量：408 passed、3 skipped（Windows 专用 CUDA 用例）、覆盖率 94.02%。
  Ruff lint、Pyright、OpenAPI 校验和 `git diff --check` 通过。
- 格式：本次修改的四个 Python 文件通过；全仓库 format check 在用户原有
  `app/ocr/journal/alignment.py` 的两处注释间距处失败，保留不改。
- Docker：实际执行 `docker compose ... config --format json` 并通过 `Settings`
  加载解析出的 API 环境，默认、false、true 分别得到关闭、关闭、开启。
- 独立审查未发现阻断；补齐 `docs/agents-api.md` 和 `interfaces/guides/agents.md`
  中遗漏的新启用条件，不修改正式 Schema 或 OpenAPI。
- 本地服务：通过项目脚本重启 API、启动原先未运行的 Ollama；
  `uv run --locked python -m scripts.common.verify_agents` 完整真实评测通过。
  Qwen3.5 9B Q4_K_M 共 62 次调用（58 次 200、4 次预期 422），用时 394.3 秒；
  日志样本集 4.0.0、意图样本集 5.0.0，无失败用例。
  报告为忽略提交的 `verification/agents-live-result.json`。
- 真实云端：临时隔离应用使用不监听的回环端口模拟本地不可达，不停止实际模型；
  合成聊天在关闭时仅请求本地并返回 503，开启时先本地再云端并返回正确答案；
  合成结构化日志也经云端返回并通过字段/事实检查，三个检查均通过。
  结果在 `verification/llm-fallback/live-switch.json`。
  临时脚本首次因继承代理收到 502，按项目脚本设置回环 `NO_PROXY` 后复验通过；
  未更改生产逻辑或降低断言。
- 实际 `.env` 保留不变，本机已配置回退密钥但未启用新开关，所以部署当前回退关闭。
  Linux/vLLM/GPU 实机部署未验证；Docker 仅验证 Compose 配置解析与应用设置加载。

实际执行的完整检查命令（设置 `UV_CACHE_DIR="$PWD/.cache/uv"`）：

```zsh
uv sync --locked --group dev --extra ocr-cpu
uv run --locked ruff check app tests scripts
uv run --locked ruff format --check app tests scripts
uv run --locked pyright
uv run --locked python -m scripts.docs.check_openapi
uv run --locked pytest -v --cov=app --cov-fail-under=85
zsh scripts/dev/services.sh restart-api
zsh scripts/dev/services.sh start
uv run --locked python -m scripts.common.verify_agents
```
