# 代码审查与渐进式重构记录

本轮以保持现有 API、数据结构、业务规则、配置及启动入口为约束。审查范围包括 `app/`、提示词与接口说明、测试、开发与生产脚本，以及已有未跟踪的 `ocr/`（包括被忽略规则隐藏的 `template_pipeline/`）。保留 `.env`、用户数据和原有未跟踪内容；没有更新依赖、提交或操作 Linux 部署。

## 架构判断

主 API 已有合理的 `路由 → 业务 Agent → 共享运行时 → 模型服务` 边界。共享基类、请求局部消息、原生结构化输出、提示词分离和生命周期管理均值得保留。当前没有持久化数据访问层，不引入仓储、额外接口或工厂层；路由数量少，也不机械拆成多个路由文件。

## 本轮修改

| 问题 | 修改 | 兼容性保障 |
| --- | --- | --- |
| `ModelService` 构造/关闭的异常路径可能遗留同步 HTTP 客户端 | 在异步客户端构造或关闭失败时尝试释放已取得的同步客户端；双重清理失败时保留原异常或取消信号，并记录不含异常正文的警告 | 正常关闭和单独同步关闭失败的传播规则保持原样；不修改模型工厂、参数或请求协议 |
| 应用工厂中混合生命周期、路由和大量 HTTP 异常处理细节 | 新增 `app/http_errors.py`，统一注册原有处理器；入口保留路由和生命周期 | 保留状态码、中文详情、参数错误脱敏和既有 `app.main` 日志通道；完整 OpenAPI 前后比较一致 |
| 业务验收脚本的单个长函数混合请求记录和各类验收 | `_VerificationClient` 负责实际请求/响应记录；日志、意图、会话分别由同文件内的场景函数验收 | 保留 `main()`、`log_matches_expectations()`、兼容入口、请求顺序、报告字段、输出内容及异常传播 |
| 异常路径和验收报告缺少针对性的保护 | 新增生命周期、精确 HTTP 错误、脱敏与失败报告测试 | 使用真实 httpx 客户端和真实应用，在外部 HTTP/transport 边界模拟故障 |

业务 Agent、Schema、提示词、历史预算、意图阈值与分支、模型配置均未修改。

目录仅增加一个生产模块：

```text
app/
  main.py          # 路由、生命周期与异常处理注册
  http_errors.py   # 原有 HTTP 错误映射与验证错误脱敏
  llm.py           # 模型工厂、就绪检查和 HTTP 资源所有权
scripts/common/
  verify_agents.py # 请求记录及日志/意图/会话验收
tests/
  test_lifecycle.py
  test_http_errors.py
  test_verify_agents.py
```

## 未混入本轮的发现

以下均来自现有代码审查。它们需要独立的修复范围和验收标准，避免借重构改变异常请求、并发或部署行为。

| 优先级 | 位置 | 发现与后续方案 |
| --- | --- | --- |
| P1 | `ocr/backend/server.py` 的 `spa()` | 直接拼接请求路径并返回文件，缺少前端目录边界检查；应优先补充解析后路径及符号链接边界校验和 HTTP 回归测试。本轮是源码安全发现，未做完整服务的实际 HTTP 利用验证。 |
| P2 | `ocr/backend/server.py` 的 `scan_templates()`、`_route_template()` 与自动匹配路由 | 全局注册表和 TTL 不按 `create_app(root)` 隔离；扫描后也多次读取可替换的全局状态。应改为应用持有的注册表和请求内快照。只读隔离复现确认不同根目录可能复用前一次扫描结果。 |
| P2 | `ocr/backend/template_pipeline/text/ocr_cells.py` 的 `_get_ocr_engine()` | `lru_cache` 不保证并发首次 miss 只构造一个实例；本地和独立 OCR 服务的并发保护也不同。隔离复现确认可重复构造；实际是否需要统一推理锁须结合 RapidOCR 压测判断，未宣称已复现真实推理并发故障。 |
| P2 | `ocr/backend/template_pipeline/semantic/match.py` 的 `match_data_fields()` | 把 `_matched` 写入调用方 `index.rows`；当前 HTTP 请求每次读 JSON 降低了影响，但不利于重用、缓存和并发。可用局部消费状态替换，需覆盖精确/模糊/歧义匹配和输入不变性。 |
| P2 | `ocr/backend/ocr_service.py` 与 `text/ocr_cells.py` | 重复维护单格识别、紧裁剪兜底和阈值过滤；建议在具备 OCR 环境后提取显式接收 engine 的识别核心，并保留各自日志与锁策略。 |
| P2 | `ocr/backend/ocr_service.py` 与 `_prepare_crop()` | 外部矩形超出图像范围或空图像数据可能进入 OpenCV 异常路径；应先确定无效格子的拒绝/跳过策略，再增加输入和裁剪检查。该修复可能改变错误状态或跳过行为。 |
| P2 | `scripts/dev/services.sh` 的 `start_job()` | 仅在调用 shell 设置的 `LLM_*`、`OLLAMA_*` 没有被显式转交给 launchd；文档所述配置优先级在这种启动场景下缺乏保障。应定义变量白名单并以模拟 launchctl 验证，不把凭据写入输出。 |
| P3 | `ocr/backend/server.py` 的 `_sheet_preview_url()` | `open(...).read()` 依赖对象回收关闭文件，可改为上下文管理器；保持哈希、命名、URL 和保留策略。因 OCR 是已有未跟踪、独立依赖的子系统，本轮统一保留原内容。 |

OCR 源码中还存在较多局部导入、宽泛异常和 `print()` 日志，但部分用于兼容脚本执行、可选依赖和逐格降级；未批量替换，以免改变原有容错行为。

## 验证记录

- 基线：234 项测试通过；Ruff 检查、格式检查通过。
- 生命周期先测后改：最初 3 项失败明确复现资源未释放；复审后增加双重失败测试，再验证原异常和取消信号的保留。纯代码移动使用先补充的行为特征测试保护。
- 最终离线回归：253 项测试通过（新增 19 项）。依赖使用 `uv sync --locked --group dev` 同步，未改锁文件。
- 完整 OpenAPI JSON 前后相同；应用内部导入图无环（17 个模块）；开发/兼容脚本通过 `zsh -n`，生产脚本通过 `bash -n`。
- AGENTS.md 的 `uv run --locked pytest tests/unit/ tests/integration/ -v` 实际执行失败：目录不存在，收集 0 项；全套验证使用仓库真实的 `uv run --locked pytest -v`。
- 未运行独立类型检查：项目未配置类型检查器，当前环境未安装 mypy/pyright；未为本轮新增依赖。
- OCR 未做完整运行和真实识别验收：业务虚拟环境缺少 OpenCV、NumPy、RapidOCR 和 multipart，且没有本轮可用的 OCR 回归图片。未跨环境安装依赖或把主 API 测试结果当作 OCR 验收结果。
- 真实模型业务验收：当前代码在随机回环端口完成 45 项业务检查，全部通过（41 次成功响应、4 次预期 422）；使用本机 `qwen3.5:9b-q4_K_M`，耗时约 213 秒。输出保存在 Git 忽略的 `verification/agents-live-result.json`。
- 额外真实推理验收：直调 Agent、进程内 ASGI、TCP HTTP、Q4_K_M 量化和 Mac GPU 分配均通过，耗时约 49 秒。报告为 `verification/live-result.json`；本轮证据副本及汇总见 `verification/refactor-2026-10-31/`。

## 执行记录

- 原有 `ocr/`、`.agents/`、`.codex/` 均保持未跟踪状态，未覆盖其内容。
- 按规范执行 `restart-api` 后，脚本因端口 8000 属于其他方式启动的进程而退出，未停止该进程。
- 当前代码的真实验收使用独立随机回环端口及自动清理的临时 API，现有端口 8000 的服务不代表已更新部署。
- 临时 API 已确认停止，验收进程正常退出（状态码 0）。
- Linux/NVIDIA/vLLM 部署未执行。
