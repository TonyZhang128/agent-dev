# APIRouter 重构审查与兼容性记录

## 范围和审查结论

本轮审查 `app.main:app` 的应用创建、路由、异常处理、Schema、Agent 业务流程和模型资源生命周期，并直接完成路由迁移。工作区已有前序未提交修改，本轮以当前内容为基线，未覆盖前序修改、`.env`、OCR 文件或用户数据，未提交 Git。

原先六个接口嵌套在 `create_app()` 中，业务注册和应用装配集中于入口。现有 `app/agents/` 已提供与 HTTP 无关的业务层，`schemas.py`、`config.py`、`llm.py`、`http_errors.py` 已有明确边界。因此只抽取领域 Router，不增加转发 Service、Core 目录或依赖获取包装。方案使用 FastAPI 官方的 [APIRouter 及 include_router](https://fastapi.tiangolo.com/tutorial/bigger-applications/) 组织方式。

## 文件职责

```text
app/
  main.py              # 应用工厂、lifespan、全局错误处理及路由注册
  api/
    __init__.py
    router.py          # 导出 api_router，按原顺序聚合三个 Router
    agents.py          # 日志、意图、聊天 HTTP 入口
    business.py        # 业务步骤规划 HTTP 入口
    system.py          # 存活与模型就绪 HTTP 入口
  agents/              # 原有业务逻辑和 LangChain 运行时
  schemas.py           # 原有严格请求/响应校验
  config.py            # 原有配置
  llm.py               # 原有模型工厂和客户端管理
  http_errors.py       # 原有全局异常处理
tests/
  test_routing.py      # 完整契约、独立挂载、系统接口及资源隔离
  fixtures/
    api-openapi.json   # 从重构前应用实际导出的完整契约
```

## 接口清单和迁移对应

迁移前均位于 `app/main.py`；以下完整路径、方法、函数名和协议保持原样。业务 Router 通过 prefix 管理公共路径、tags 管理原分组；系统接口保留原无 tags 的元数据。

| 方法与完整路径（迁移前后相同） | 迁移位置 | 请求体 | 成功响应 / response_model | 原分组 / summary |
| --- | --- | --- | --- | --- |
| `GET /health` | `api/system.py:health` | 无 | 200 `{"status":"ok"}` / 无 | 无 / 自动生成 Health |
| `GET /ready` | `api/system.py:ready` | 无 | 200 `{"status":"ready"}` / 无 | 无 / 自动生成 Ready |
| `POST /api/business/plan` | `api/business.py:plan` | `PlanRequest` | 200 `BusinessPlan` | 业务规划 / 生成业务步骤 |
| `POST /api/agents/log-summary` | `api/agents.py:log_summary` | `LogSummaryRequest` | 200 `LogSummary` | 智能体 / 总结并生成工作日志 |
| `POST /api/agents/intent` | `api/agents.py:intent` | `IntentRequest` | 200 `IntentResult` | 智能体 / 识别页面导航或一般交流意图 |
| `POST /api/agents/chat` | `api/agents.py:chat` | `ChatRequest` | 200 `ChatResponse` | 智能体 / 自由对话 |

- 六个接口均无 Query、Path、Header 参数。业务 JSON 均要求 `user_id`、`session_id`，intent/chat 要求 `history`；请求体字段、约束及响应字段见未修改的 Schema 和完整基线 fixture。
- 原有 description 为空；未显式指定 status_code、自定义 dependencies 或其他额外响应配置。完整 OpenAPI 比较同时覆盖 operationId、tags、summary、JSON Schema、200/422 声明、标题和版本。
- 原来没有自定义鉴权、路由依赖或用户中间件，本轮保持不变；调用方身份字段仍不代表认证。内置 `/docs`、`/redoc`、`/openapi.json` 及 OAuth 重定向入口保持。
- `http_errors.py` 不变：校验/上下文预算异常 422、模型不可达 503、超时 504、上游或非法输出 502；错误 JSON 仍为 `detail`，保持脱敏及原日志通道。`/ready` 保留自身的 503 中文详情。
- 所有接口保留 `async def` 和原 `await`，未添加阻塞操作；四个业务路由仅将 Pydantic 请求传给现有 Agent。

## 资源和导入边界

`create_app(service=None)` 及 `app = create_app()` 入口不变。lifespan 的初始化顺序、`try/finally`、共享 ChatAgent 注入 IntentAgent、服务关闭行为保持原样。模块级 Router 只保存注册信息；路由通过当前 `request.app.state` 取得资源，无模块级模型/Agent，无每次请求构造。未引入存储、会话共享或新的并发锁。

依赖方向为 `main → api.router → 领域 Router → schemas`，系统 Router 只额外引用已有 HTTP/上游异常类型，不导入 main。原有 Agent 仍通过统一运行时调用模型。

## 验证

- 基线全套测试：253 项通过。
- 新增 10 项测试先执行：9 项现有行为特征测试通过，1 项因缺少 `app.api` 失败（RED）；迁移后针对性 164 项回归通过（GREEN）。
- 完整 OpenAPI JSON 前后相同；独立比较确认 6 个唯一异步接口、无重复注册、遗漏或路径变化；22 个应用模块静态导入图无环。
- 锁定依赖同步通过，未修改依赖；Ruff lint 和 49 个 Python 文件的格式检查通过。
- 最终全套 `uv run --locked pytest -v`：263 项通过（新增 10 项），耗时 16.55 秒；输出保存在 `verification/apirouter-2026-10-31/pytest.txt`。
- 实际执行 `pytest tests/unit/ tests/integration/ -v` 返回退出码 4，原因是这两个目录不存在，收集 0 项；完整测试使用仓库实际的 `pytest -v`。
- 按仓库要求尝试 `scripts/dev/services.sh restart-api`：端口 8000 被其他方式启动的进程占用，脚本退出，未停止它。该既有服务不能作为本轮部署完成的证据。
- 沙箱最初禁止监听本地端口，经正规提权后，在随机回环端口启动当前 `app.main:app` 完成 TCP HTTP 验证：health/ready 均为 200，完整 OpenAPI 与基线相同，四个业务空请求均为 422；一次真实 `qwen3.5:9b-q4_K_M` 聊天返回 200 且符合原响应结构。临时 API 已自动停止，记录为 `verification/apirouter-2026-10-31/startup-result.json` 和 `startup.log`。
- 独立只读复审未发现严重或重要问题：核对六个端点函数体与原实现一致、重构前 OpenAPI/fixture/当前 OpenAPI 三者一致，并独立执行 routing/lifecycle/http_errors 共 25 项测试，全部通过。复审不评价前序无关修改、独立 OCR、模型质量或 Linux 部署；本记录的最终全套及临时启动证据由主执行者另行核实。

## 边界与待处理事项

- `ocr/` 包含两个独立 FastAPI 应用、独立依赖和启动方式，且当前整体未跟踪，不属于 `app.main:app`；本次没有合并、迁移或验证其接口。前序发现见 [已有代码审查记录](code-review-2026-10-31.md#未混入本轮的发现)。
- 未改业务算法、提示词、推理协议或模型配置；离线测试使用真实 LangChain Agent，在外部 HTTP 边界模拟模型。未重复运行 45 项完整真实业务评测，仅执行上述真实聊天冒烟验证。
- Linux/NVIDIA/vLLM 部署未执行。没有新增依赖或独立类型检查器。
- 本轮静态审查与运行验证未发现主应用路由迁移中的额外阻断问题。
