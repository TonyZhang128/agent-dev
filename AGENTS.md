# 项目开发与 AI 协作规范

本文件适用于整个仓库，供开发者和编程代理共同遵守。默认使用中文沟通，命令、标识符和必要的专业术语保留原文。`CLAUDE.md` 引用本文件，不另外维护一套项目规则。

## 一、项目定位与工作边界

- 主应用入口为 `app.main:app`，默认监听 `127.0.0.1:8309`；技术栈为 Python 3.12、uv、FastAPI、Pydantic 和 LangChain 1.x。
- macOS 开发使用 Ollama；Linux 部署使用独立的 vLLM 服务，通过 `.env` 中的 OpenAI 兼容端点切换。业务环境与模型服务环境分离。
- 当前提供工程日志总结、意图识别和聊天三类业务；尚未接入审批、订单修改、通知发送等外部业务动作，也没有数据库或服务端持久会话。
- 工作区中的 `ocr/` 是独立应用，有自己的依赖和启动方式，未挂载到主应用。修改前阅读其 README；不要把主应用的检查结果当作 OCR 验收，也不要擅自合并环境、路由或依赖。
- `../docsvc` 的文档加工功能已合并到 `app/ocr/`，由 `app/api/ocr.py`、`app/api/wbs.py` 接入同一主应用；它与上面的未跟踪 `ocr/` 是不同项目。模板与数据路径见 `docs/ocr.md`，脚本统一为 `scripts/ocr/`。
- 以当前源码、配置、锁文件和实际测试为依据。历史审查报告记录当时结果，不代表当前部署已更新或当前测试必然通过。

## 二、开始工作前

1. 阅读 `README.md`、`pyproject.toml` 和受影响模块；HTTP 契约见 `docs/agents-api.md`，会话规则见 `docs/sessions.md`，脚本入口见 `scripts/README.md`。
2. 检查 `git status --short` 和相关 diff，区分已有修改与本次修改，保留未提交文件、`.env`、用户数据、模型及其他应用内容。
3. 先检查已安装工具和项目环境。macOS 系统工具使用 Homebrew，项目依赖使用 uv；禁止安装到系统 Python 或其他项目环境。
4. 明确验收标准、变更范围和现有失败。发现无关问题时记录原因，不夹带修复、不批量覆盖或回滚用户修改。
5. 对已授权任务直接推进实现与验证；遇到可通过正规权限申请解决的限制时，申请最小必要权限，并说明用途。不得绕过隔离或虚构审批结果。

## 三、目录职责与依赖方向

| 位置 | 职责与约束 |
| --- | --- |
| `app/main.py` | 应用工厂 `create_app()`、lifespan、共享资源初始化与清理、全局异常处理注册和 `include_router()`；不放具体业务路由或提示词 |
| `app/api/router.py` | 统一聚合领域 Router；同一个领域仅注册一次 |
| `app/api/agents.py` | `/agents` 下的日志、意图、聊天入口；分组为“智能体” |
| `app/api/system.py` | `/health`、`/ready`；保留原路径和 OpenAPI 元信息 |
| `app/schemas.py` | Pydantic 请求、响应与校验；拒绝额外字段，保留长度、枚举及跨字段约束 |
| `app/agents/` | 与 HTTP 请求对象无关的业务逻辑；复用共享基类和运行时 |
| `app/prompts/<name>.md` | 系统提示词，使用 `load_prompt()` 加载 |
| `app/config.py` | `Settings`、配置默认值及配置校验 |
| `app/llm.py` | `ChatOpenAI` 工厂、HTTP 客户端及模型列表就绪检查；不放业务规则 |
| `app/ocr/` | 从 docsvc 迁入的照片/简表识别、公式/引用、PDF/Excel 填表、WBS；不得反向导入 scripts 或 FastAPI |
| `app/api/ocr.py`、`app/api/wbs.py` | 文档加工入口、数据池路径限制和文档异常 HTTP 映射；原 `/health` 优先 |
| `scripts/ocr/` | 模板生成、PDF/Excel 检查和演示工具，使用主项目 Python 3.12 环境 |
| `app/errors.py`、`app/http_errors.py` | 前者定义非 HTTP 业务/模型异常，后者负责统一 HTTP 映射及错误脱敏 |

依赖方向保持为 `main → 路由聚合 → 领域 Router → Schema/业务资源`。Router 不导入 `app.main` 或全局 `app`；业务层不依赖 FastAPI `Request`、`HTTPException` 或响应对象。当前 `app/agents/` 已承担业务层职责，不为目录整齐增加只做转发的 Service、Repository 或 Core 层。

### 路由与生命周期

- 业务接口一律使用 `APIRouter`，公共路径使用 `prefix`，文档分组使用 `tags`，由主应用统一注册。检查完整路径，避免前缀重复、遗漏和重复注册。
- 保留原有方法、参数、`response_model`、summary、description、operationId、状态码及依赖配置；保留同步/异步语义和 `await` 关系，不在异步路由中引入阻塞耗时操作。
- 模型服务及 Agent 在 lifespan 中初始化，路由通过当前 `request.app.state` 获取；确有复用价值时可使用 `Depends()`，不为形式增加包装。
- 禁止每次请求重建昂贵资源、在模块全局持有模型实例，或跨应用共享可变状态。保留共享 ChatAgent 注入 IntentAgent 的关系。
- 使用 `@asynccontextmanager` 管理启动与关闭，异步生成器注解使用 `AsyncGenerator[None, None]`；初始化后的资源释放放入 `try/finally`，覆盖启动失败和关闭异常路径。不改回旧的 `on_event` 写法。
- `ModelService` 持有的同步、异步 HTTP 客户端，包括注入的客户端，均由其关闭；不得因清理异常丢失原始异常或取消信号。

### Agent 与推理

- 所有业务 Agent 复用 `app/agents/base.py`：结构化业务继承 `StructuredAgent[请求, 结果]`，其他业务继承 `BaseAgent[请求, 结果]`。公共需求优先扩展基类，不复制提示词加载、构建和调用流程。
- 推理统一经过 `app/agents/runtime.py` 的 `build_agent()` / `invoke_agent()`，使用 `langchain.agents.create_agent()`；不新增直接调用 SDK 的推理旁路，不使用 `AgentExecutor`、`initialize_agent` 等旧 API。
- 结构化输出使用 `ProviderStrategy(schema, strict=True)` 原生 JSON Schema，再用 Pydantic 校验。不得回退到宽松文本解析或伪造成功结果。
- 使用 LangChain 消息、工具与中间件；`@tool` 通过 `build_agent(..., tools=...)` 注册，保留响应检查、总超时和递归限制。
- 编译后的 Agent 可复用，但消息、动态 Schema 和执行状态必须请求隔离，不修改共享 Agent，不启用 checkpointer 或隐式持久历史。

## 四、必须保持的 API 契约

| 方法与路径 | 请求模型 | 响应模型 |
| --- | --- | --- |
| `POST /agents/log-summary` | `LogSummaryRequest` | `LogSummary` |
| `POST /agents/intent` | `IntentRequest` | `IntentResult` |
| `POST /agents/chat` | `ChatRequest` | `ChatResponse` |

- 三类业务均要求 `user_id`、`session_id`；intent/chat 还要求当前会话完整 `history`，首轮为 `[]`；日志拒绝 history。
- 身份通过请求局部 LangChain metadata 传递，不写入模型提示词。调用方 ID 不等于身份认证；当前应用没有自定义认证机制。
- 历史仅接受完整、交替的 user/assistant 回合，拒绝调用方 system 消息。使用共享历史工具按上下文预算裁剪最早完整回合，保留当前输入和系统提示词；遵守完整输入上限，不恢复旧的 10 条消息或 4000 字符会话限制。UTF-8 字节估算是保守预算，不是精确 tokenizer。
- 日志接受文字或 JSON 对象，保留原始事实、数值和单位；不得虚构日期、成果、任务或合格结论。具体字段约束以 Schema 和 `interfaces/log_summary/` 为准。
- 意图固定为 `work_list`、`supervision_log`、`image_library`、`business_management`、`chat` 五类，加 `unknown` 兜底。`intents` 只能省略或为 `[]`，非空在推理前返回 422。
- 意图分数低于 `0.65` 或需要澄清时必须回退 `unknown` 且 `needs_clarification=true`；分数不是校准概率。有效 `chat` 继续调用共享 ChatAgent，将回答放入 `reason`，两次推理共享总超时；不因聊天失败返回分类理由冒充答案。
- `/health` 只检查进程存活；`/ready` 通过模型列表检查配置模型，不执行推理。
- 文档接口新增 `/health/deps`、`/ocr/*`、`/wbs/draft`；成功保留 `{"status":200,"data":...}`。模板和 OCR 引擎按需加载，应用资源保存在 `app.state.ocr_resources`，缓存与模型不得跨应用串用；缺模板仅影响相关请求。
- OCR 路径由 Settings 的 `TEMPLATES_ROOT`、`ADMIN_ROOT`、`ASSET_ROOT`、`PROJECTS_ROOT` 配置；相对路径以仓库根目录解析。输入输出不得越过数据池，空 out 不写文件；辅助脚本的报告/打包输出写到忽略提交的 `verification/ocr/`。
- 字段 ID、格子键和坐标语义沿用 docsvc；保留隐藏文字层过滤、OCR 锁、模板引用优先级与 JS 风格舍入。Excel 跳过字段通过本次 `ExcelOutput` / `xlsxSkipped` 返回，不恢复共享函数属性。
- 错误状态保持：非法输入/上下文超限 422，模型不可达 503，推理超时 504，上游错误或非法输出 502。统一保留 `detail` 响应，禁止泄露密钥、原始输入、身份、历史和上游错误正文。

## 五、新增业务的流程

1. 先定义验收标准和正常、边界、失败用例，再增加测试。
2. 在 `app/schemas.py` 定义请求/响应，在 `app/prompts/` 增加提示词。
3. 在 `app/agents/` 继承共享基类。结构化业务实现 `name`、`result_type`、`user_content()`；其他业务实现 `name`、`messages()`、`parse_result()`。意图分类内部 Schema 与最终响应有区别，参照现有 `intent.py`，不要机械合并。
4. 在 `main.py` 的 lifespan 中创建共享实例，在对应领域 Router 中增加 HTTP 入口和 `response_model`；新增领域时创建 Router 并在 `app/api/router.py` 注册。
5. 补齐契约、资源隔离、错误及必要的并发测试；同步 API 文档、README 目录和接口示例。
6. 对有外部副作用的工具，先设计身份、授权、幂等和业务确认，再接入实际系统；当前内容生成能力不代表获得执行业务动作的权限。

## 六、测试、契约快照与验收

- 功能和行为修复遵循测试驱动开发：先写测试，确认因预期行为缺失失败（RED），再最小实现（GREEN），最后保持测试通过进行整理（REFACTOR）。行为修复应包含原故障的回归用例。
- 纯文档、排版或类型注解调整按实际影响验证，不添加只匹配源码文字、没有行为价值的测试。
- 纯业务逻辑用单元测试，跨模块用契约/集成测试；只在外部 LLM、OCR、HTTP 等边界模拟，不模拟被测实现。真实模型评测独立运行，使用版本化数据集和明确成功标准。
- 测试文件目前直接放在 `tests/test_*.py`，数据在 `tests/fixtures/`；不要运行不存在的 `tests/unit/`、`tests/integration/`，也不要为符合旧命令擅自搬动测试。
- `tests/test_routing.py` 与 `tests/fixtures/api-openapi.json` 保护完整 OpenAPI、唯一注册、Router 独立挂载和资源隔离。标题、版本、operationId 和 tags 都属于比较范围。
- 快照失败先审查实际差异：非预期变化修实现；已明确确认的契约或元信息变更，在核对完整差异后同步文档和快照。不得自动重录整个快照、删除断言、跳过或弱化测试来制造通过。

在仓库根目录执行与 CI 一致的检查：

```zsh
export UV_CACHE_DIR="$PWD/.cache/uv"
uv sync --locked --group dev
uv run --locked ruff check app tests scripts
uv run --locked ruff format --check app tests scripts
uv run --locked pytest -v
```

离线测试使用真实 LangChain Agent 和模拟模型 HTTP 响应，不要求 Ollama、联网或云端凭据；首次准备依赖可能需要网络。可先运行相关文件或 `pytest -k`，交付代码变更前执行全套检查。生产 `--no-dev` 环境不临时安装开发依赖。

涉及推理协议、提示词、模型配置或 Agent 流程时，重启对应 API 并进行真实模型验收：

```zsh
zsh scripts/dev/services.sh restart-api
uv run --locked python -m scripts.common.verify_agents
# 涉及 Ollama、GPU 或开发部署脚本时额外运行：
uv run --locked python -m scripts.dev.verify_live
```

Linux 使用 `scripts/prod/` 对应入口；远端业务验收使用 `BUSINESS_API_URL`。业务验收访问的 API 与直调验收所用 `LLM_*` 配置应指向同一目标部署。输出写入 Git 忽略的 `verification/`，不提交真实业务输入或追踪。

离线通过不代表部署成功。遇到非本项目启动的端口占用时保留原进程，说明未更新该部署；可用临时回环端口验证新代码，结束后清理自己启动的进程。仅修改文档不需要重启服务或触发真实推理。

## 七、配置、依赖与运维

- 项目固定 Python 3.12；Ruff 负责基础 lint、导入排序和格式。遵循现有命名和类型注解，不为本次任务无关的风格批量重写。
- 注释和 docstring 统一使用中文；标识符、命令、路径、环境变量和必要技术术语保留原文。新增或修改代码时保持该风格，翻译注释不得改变代码行为。
- 依赖通过 `uv add` 管理，`pyproject.toml` 和 `uv.lock` 一起更新，禁止手改锁文件。固定已验证的 `langchain`、`langchain-core`、`langchain-openai`；升级前查官方文档与 provider 兼容性，不引入不必要框架。
- `Settings` 的读取顺序为 API 进程环境、根目录 `.env`、源码默认值；新增配置同步更新 `Settings`、`.env.example` 和 README，保留本机 `.env`。
- launchd 启动的后台任务不保证继承当前终端临时导出的所有变量。持久业务配置优先维护根目录 `.env`，不要声称 `export LLM_*` 或 `OLLAMA_*` 一定传入后台任务；Ollama 自身配置需由其实际启动环境提供。
- `LANGSMITH_TRACING=false` 为默认值，只有显式配置才启用；凭据运行时注入，不记录或提交真实业务 traces。`SecretStr` 不替代日志、错误和提交内容的脱敏。
- 使用 `scripts/dev/services.sh` 管理本项目 Mac 任务。frp 公网接入仅用于开发联调，生产部署不安装、不启动 frpc/frps；普通 `start` 不启动 frp，`stop` 会先停止本项目 frpc，再处理 API/Ollama；不停止其他方式启动的进程，不编辑 shell profile。
- 日志在 `.logs/`，模型由 Ollama 或独立 vLLM 环境管理；密钥、隧道凭据和私有证书在受控运行环境或 `.secrets/`，不写入业务代码、命令输出或仓库。
- 公网隧道仅用于开发期接入，不等于增加身份认证；主应用的用户/会话 ID 仍不提供权限保护。生产环境不包含 frp，生产暴露或外部动作的权限设计应单独明确。

## 八、Git 与交付要求

- 保持 `origin` 为 `https://github.com/TonyZhang128/agent-dev.git`，尊重现有分支、历史和用户修改。不执行破坏性清理、强制推送或覆盖式回退。
- 提交前检查 `git diff --check`、暂存 diff 和状态，只提交本任务文件/修改块；避免在脏工作区直接 `git add .` 或批量暂存整个目录。
- 排除 `.env`、`.secrets/`、模型、`.venv/`、缓存、日志、验收输出及本地 `skills/`；已有未跟踪目录不因本任务自动纳入提交。
- `README.md` 面向使用和开发，`AGENTS.md` 维护共享规则，`docs/` 保存详细契约及专题说明；更新时核对实际脚本和目录，避免重复维护相互矛盾的规则。
- 包版本以 `pyproject.toml` 为准，OpenAPI 标题/版本以 `FastAPI(...)` 为准。二者当前不同；不要擅自统一，修改时说明含义并处理相关契约快照。
- 交付简要说明修改文件、原因、实际执行的检查、已有失败/未验证风险、启动方法及项目路径。未执行的测试、真实模型验证、部署或 Linux GPU 验收不得宣称通过。

## 九、可选本地技能

对应文件存在时，相关工作先阅读并遵循；本地 `skills/` 已被 Git 忽略，干净克隆不要求存在。

| 工作类型 | 文件 |
| --- | --- |
| LangChain Agent、工具、结构化输出 | `skills/langchain-fundamentals/SKILL.md` |
| LangChain 依赖调整 | `skills/langchain-dependencies/SKILL.md` |
| 检索与知识库 | `skills/langchain-rag/SKILL.md` |
| LangGraph 状态和工作流 | `skills/langgraph-fundamentals/SKILL.md` |

来源：<https://github.com/langchain-ai/langchain-skills>，固定修订 `16a992f09ab3ccfb642dd4f08d350d833d1990bf`。使用仓库本地 `skills/`，不要求写入受保护的 `.agents/` 或 `.codex/`；用户明确指令和仓库实际约束优先。
