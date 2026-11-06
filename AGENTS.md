# 项目开发与 AI 协作规范

本文件适用于整个仓库，供开发者和编程代理共同遵守。默认使用中文沟通，命令、标识符和必要的专业术语保留原文。`CLAUDE.md` 引用本文件，不另外维护一套项目规则。

## 一、项目定位与工作边界

- 主应用入口为 `app.main:app`，默认监听 `127.0.0.1:8309`；技术栈为 Python 3.12、uv、FastAPI、Pydantic 和 LangChain 1.4.6。
- macOS 开发使用 Ollama；Linux 部署使用独立的 vLLM 服务，通过 `.env` 中的 OpenAI 兼容端点切换。业务环境与模型服务环境分离。
- 当前提供工程日志总结、意图识别和聊天三类业务；尚未接入审批、订单修改、通知发送等外部业务动作，也没有数据库或服务端持久会话。
- 工作区中的 `ocr/` 是独立应用，有自己的依赖和启动方式，未挂载到主应用。修改前阅读其 README；不要把主应用的检查结果当作 OCR 验收，也不要擅自合并环境、路由或依赖。
- `../docsvc` 的文档加工功能已合并到 `app/ocr/`，由 `app/api/ocr.py`、`app/api/wbs.py` 接入同一主应用；它与上面的未跟踪 `ocr/` 是不同项目。模板与数据路径见 `docs/ocr.md`，脚本统一为 `scripts/ocr/`。
- 以当前源码、配置、锁文件和实际测试为依据。历史审查报告记录当时结果，不代表当前部署已更新或当前测试必然通过。

## 二、开始工作前

1. 阅读 `README.md`、`pyproject.toml` 和受影响模块；先检查 `interfaces/` 是否有正式契约或待确认草案，HTTP 细节见 `docs/agents-api.md`，会话规则见 `docs/sessions.md`，脚本入口见 `scripts/README.md`。
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
| `app/api/system.py` | `/health`、`/ready`、`/diagnostics`；存活、模型就绪与本地依赖诊断 |
| `app/schemas/` | Pydantic 请求、响应与校验；`base.py` 共用严格模型与会话基础类型，`agents.py` 智能体业务，`ocr.py` 文档加工；拒绝额外字段，保留长度、枚举及跨字段约束 |
| `app/agents/` | 与 HTTP 请求对象无关的业务逻辑；复用共享基类和运行时；扁平归档意图在 `profiles.py` 声明，业务端层级意图由 `app/resources/intent/business_pages.json` 与 `intent_catalog.py` 派生 |
| `app/resources/intent/` | 业务页面/二级功能 JSON 唯一数据源；构建期由 `scripts.intent.compile_catalog` 生成枚举，应用运行时不读取 |
| `app/prompts/<name>.md` | 系统提示词，使用 `load_prompt()` 加载；可按能力分子目录，如 `intent/business.md` |
| `app/config.py` | `Settings`、配置默认值及配置校验 |
| `app/llm.py` | `ChatOpenAI` 工厂、HTTP 客户端及模型列表就绪检查；不放业务规则 |
| `app/ocr/` | 从 docsvc 迁入的文档加工,按业务分子包:`core/`(资源隔离、CUDA 运行库、依赖自检、OCR 引擎、图像/PDF 原语、扫线、按配置格子的照片识别链 sheet_scan、版面元数据 layouts)、`form/`(现场照片模板对齐识别、栏目正则)、`sheets/`(表样格子提取与 Excel 写出)、`jianbiao/`(简表版面与识别编排、公式/引用填表)、`daily_logs.py`(旧监理日志逐格识别)、`journal/`(新版监理日志：定位、单次整页 OCR、栏目匹配，独立于旧链)、`wbs_draft.py`(划分初稿);不得反向导入 scripts 或 FastAPI |
| `app/api/ocr.py`、`app/api/wbs.py` | 文档加工入口、数据池路径限制和文档异常 HTTP 映射；原 `/health` 优先 |
| `scripts/ocr/` | 模板生成、PDF/Excel 检查和演示工具，使用主项目 Python 3.12 环境 |
| `scripts/docs/` | OpenAPI 草案导出、契约漂移检查；不得写入正式契约目录 |
| `interfaces/` | 对外接口唯一入口：正式契约、待确认草案、业务指南、变更记录；规则见第四节 |
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

## 四、接口契约与 API-First 开发流程

接口契约优先（API-First）：**先定义、先确认、后开发**。接口文档可以由 AI 生成，但已确认契约的修改权属于用户。任何 AI 自主开发行为都不得绕过用户对接口契约的最终决定权。

### 4.1 权威来源与目录

- `interfaces/` 是对外接口文档的唯一入口，`interfaces/README.md` 是索引和全局规范。
- `interfaces/openapi/` 保存用户已批准的正式 OpenAPI 契约，是接口实现的权威依据。当前完整契约尚未批准，只有三个已确认的响应子 Schema 位于 `interfaces/log_summary/`、`interfaces/intent/`。
- `interfaces/drafts/` 保存 AI 归纳或设计的待确认草案，不能作为实现授权。
- `interfaces/guides/` 保存业务流程、状态、超时、重试、路径和同步/异步语义等 Markdown 说明；不重复 OpenAPI 已包含的字段表。
- `interfaces/CHANGELOG.md` 记录契约变更；Git 历史保留版本证据。
- `docs/` 保存实现细节、测试方法和专题说明，不替代 `interfaces/` 的对外契约。
- 运行时 `/openapi.json`、`/docs` 和 `create_app().openapi()` 是当前实现的投影，便于调试，**不是正式契约**。自动生成结果不得覆盖正式契约。

### 4.2 已确认契约保护（最高优先级）

AI 不得在未经用户明确批准的情况下修改任何已确认接口契约。以下均属于契约变更，无论是否向后兼容：

- 新增、删除或修改接口路径及 HTTP 方法。
- 修改请求或响应字段的名称、类型、结构、必填性、默认值或约束。
- 新增或删除请求、响应字段。
- 修改响应包装、状态码、错误码及其语义。
- 修改认证、授权、权限或其他对外行为。
- 调整可能影响调用方的业务语义、超时、幂等、分页、文件上传或异步行为。

禁止为了让代码运行、通过测试、简化实现或解决前后端不一致而擅自修改接口文档或正式契约。代码与正式契约不一致时，必须报告差异，由用户决定修代码还是调整契约，不能默认以代码为准自动覆盖文档。

### 4.3 新增与变更流程

任何涉及 API 的新功能或接口修改，开始前先检查 `interfaces/`：

1. 已有正式契约且已确认：严格按契约开发，不自行扩展或收窄。
2. 没有正式契约或定义不完整：可以在 `interfaces/drafts/` 生成接口设计草案，但必须标记 `pending-review`。
3. 提交用户确认时说明：涉及的接口和字段、请求/响应结构、行为变化、对前端/后端/Java 等调用方的兼容性影响、必要的 OpenAPI 修改前后差异。
4. 用户批准前暂停该接口的实现；用户未回复、未明确批准或仅要求继续开发，均不代表同意。
5. 批准后先更新正式契约和 `interfaces/CHANGELOG.md`，再修改实现、测试和调用方类型。
6. 完成实现后运行契约校验和契约测试，确认实现与契约一致。

现有但没有正式契约的接口可以批量整理为 OpenAPI 草案，但必须标记为「待确认」，不能因为代码已经存在就视为用户已确认。新增接口严格按“需求分析 → OpenAPI 草案 → 用户确认 → 正式契约 → 功能开发 → 契约测试 → 交付”执行；开发中需要改接口时重新进入审批流程。不得以提高开发效率、先跑通功能或方便联调为由绕过接口设计与确认流程。

不改变对外行为的内部重构、性能优化、算法改进和 Bug 修复可以正常开发，无需接口审批，但不得借此改变接口行为。

### 4.4 AI 自主权限

AI 可以自主执行：

- 阅读、分析接口文档和调用方代码。
- 根据现有代码生成待确认 OpenAPI 草案和 Markdown 说明。
- 为缺失接口提出设计方案。
- 检查契约与实现的一致性，报告差异。
- 生成 Swagger UI 预览、Mock 数据和客户端类型。
- 优化内部算法、重构代码、修复不影响接口契约的问题。
- 补充不改变契约的解释性文档。
- 提出接口改进建议和变更方案。

AI 必须获得用户明确批准后才能：

- 将新增接口草案提升为正式契约。
- 修改任何已确认的正式契约。
- 为适配代码实现而调整接口定义。
- 对已确认接口进行兼容性或破坏性变更。

AI 可以设计接口方案，但无权批准自己的草案，也不能把“继续开发”“先跑通”解释为批准。

### 4.5 一致性与自动校验

- 已确认的 OpenAPI 是实现的权威依据；不得用实现自动覆盖正式契约。
- 优先使用 `scripts/docs/check_openapi.py` 和 `tests/test_interfaces_contract.py` 检测漂移。
- `uv run --locked python -m scripts.docs.export_openapi` 只导出 `interfaces/drafts/fastapi.openapi.json`，脚本拒绝写入 `interfaces/openapi/`；正式契约只能由用户批准后人工提升。
- `uv run --locked python -m scripts.docs.render_api_markdown` 将同一契约渲染为 `interfaces/API.md` 评审文档；该文件是只读视图，不是独立契约，不得手工修改并反向覆盖 OpenAPI。
- 契约或快照失败时先审查完整差异：非预期变化修实现；已确认的契约变更在核对差异、更新文档和 `CHANGELOG` 后同步契约。不得自动重录全量快照、删除断言、跳过或弱化测试来制造通过。
- 接口自动生成工具不得静默覆盖正式契约；运行时 `/docs` 只用于调试。

### 4.6 现有 API 契约

| 方法与路径 | 请求模型 | 响应模型 |
| --- | --- | --- |
| `POST /agents/log-summary` | `LogSummaryRequest` | `LogSummary` |
| `POST /agents/intent/business` | `BusinessIntentRequest` | `BusinessIntentResult` |
| `POST /agents/intent/archive` | `IntentRequest` | `ArchiveIntentResult` |
| `POST /agents/chat` | `ChatRequest` | `ChatResponse` |

- 三类业务均要求 `user_id`、`session_id`；业务意图还要求 `message`、`current_page`；归档端/聊天要求完整 `history`，首轮为 `[]`。业务意图的 `history` 可选，省略即 `[]`；日志拒绝 history。
- 身份通过请求局部 LangChain metadata 传递，不写入模型提示词。调用方 ID 不等于身份认证；当前应用没有自定义认证机制。
- 历史仅接受完整、交替的 user/assistant 回合，拒绝调用方 system 消息。使用共享历史工具按上下文预算裁剪最早完整回合，保留当前输入和系统提示词；遵守完整输入上限，不恢复旧的 10 条消息或 4000 字符会话限制。UTF-8 字节估算是保守预算，不是精确 tokenizer。
- 日志接受文字或 JSON 对象，保留原始事实、数值和单位；不得虚构日期、成果、任务或合格结论。具体字段约束以 Schema 和 `interfaces/log_summary/` 为准。
- 业务端意图的页面/功能编码唯一来源为 `app/resources/intent/business_pages.json`，构建期生成枚举，运行时不读取 JSON；只允许返回目录内 `page/action`。响应使用 `status`（`resolved`/`clarify`/`chat`/`unknown`）、`page`、`action`、`confidence`、`message`、`options` 和 `catalog_version`。`resolved` 必须带合法 `action`；仅一级意图返回 `clarify` 并调用 Chat 澄清，调用方传 `pending_clarification.attempts`，同一页面最多 10 轮。归档端使用独立 profile，当前固定为 `A`、`B`、`C`、`D` 加 `unknown`，不含聊天分流。
- 业务意图不持久化会话、不跟踪前端跳转；`current_page`、`last_navigation`、`pending_clarification` 由调用方传入。分类分数低于 `0.65`、同页动作不确定或需要澄清时返回 `clarify`；目录外或跨页无法确定返回 `unknown`；有效 `chat` 调用共享 ChatAgent，将回答放入 `message`。非法编码、`action` 不属于 `page` 或结构不合法返回 502。
- `/health` 只检查进程存活；`/ready` 通过模型列表检查配置模型，不执行推理；`/diagnostics` 只做本地运行库、推理设备、模板与数据池的静态检查，不初始化引擎、不访问网络，`ok=false` 仍返回 200。
- 文档接口新增 `/diagnostics`、`/ocr/*`、`/wbs/draft`；成功保留 `{"status":200,"data":...}`。模板和 OCR 引擎按需加载，应用资源保存在 `app.state.ocr_resources`，缓存与模型不得跨应用串用；缺模板仅影响相关请求。
- OCR 路径由 Settings 的 `TEMPLATES_ROOT`、`ADMIN_ROOT`、`ASSET_ROOT`、`PROJECTS_ROOT` 配置；相对路径以仓库根目录解析。输入输出不得越过数据池，空 out 不写文件；辅助脚本的报告/打包输出写到忽略提交的 `verification/ocr/`。
- 字段 ID、格子键和坐标语义沿用 docsvc；保留隐藏文字层过滤、OCR 锁、模板引用优先级与 JS 风格舍入。Excel 跳过字段通过本次 `ExcelOutput` / `xlsxSkipped` 返回，不恢复共享函数属性。
- 错误状态保持：非法输入/上下文超限 422，模型不可达 503，推理超时 504，上游错误或非法输出 502。统一保留 `detail` 响应，禁止泄露密钥、原始输入、身份、历史和上游错误正文。

## 五、新增业务的流程

1. 先定义验收标准和正常、边界、失败用例，再增加测试。
2. 在 `app/schemas/` 对应模块（智能体业务为 `agents.py`，文档加工为 `ocr.py`）定义请求/响应，在 `app/prompts/` 增加提示词。
3. 在 `app/agents/` 继承共享基类。结构化业务实现 `name`、`result_type`、`user_content()`；其他业务实现 `name`、`messages()`、`parse_result()`。意图分类内部 Schema 与最终响应有区别，参照 `intent_business.py`（层级）或 `intent.py`（扁平归档），不要机械合并。
4. 在 `main.py` 的 lifespan 中创建共享实例，在对应领域 Router 中增加 HTTP 入口和 `response_model`；新增领域时创建 Router 并在 `app/api/router.py` 注册。
5. 补齐契约、资源隔离、错误及必要的并发测试；按第四节先确认接口契约，再同步 `interfaces/`、API 文档、README 目录和接口示例。
6. 对有外部副作用的工具，先设计身份、授权、幂等和业务确认，再接入实际系统；当前内容生成能力不代表获得执行业务动作的权限。

## 六、测试、契约快照与验收

- 功能和行为修复遵循测试驱动开发：先写测试，确认因预期行为缺失失败（RED），再最小实现（GREEN），最后保持测试通过进行整理（REFACTOR）。行为修复应包含原故障的回归用例。
- 纯文档、排版或类型注解调整按实际影响验证，不添加只匹配源码文字、没有行为价值的测试。
- 纯业务逻辑用单元测试，跨模块用契约/集成测试；只在外部 LLM、OCR、HTTP 等边界模拟，不模拟被测实现。真实模型评测独立运行，使用版本化数据集和明确成功标准。
- 测试文件目前直接放在 `tests/test_*.py`，数据在 `tests/fixtures/`；不要运行不存在的 `tests/unit/`、`tests/integration/`，也不要为符合旧命令擅自搬动测试。
- `tests/test_routing.py` 与 `tests/fixtures/api-openapi.json` 保护完整 OpenAPI、唯一注册、Router 独立挂载和资源隔离。标题、版本、operationId 和 tags 都属于比较范围。
- `tests/test_interfaces_contract.py` 保护 `interfaces/` 契约与当前实现同步；有正式契约时以正式契约为准，否则检查待确认草案。契约失败按第六节和第四节处理，不得跳过。
- 快照失败先审查实际差异：非预期变化修实现；已明确确认的契约或元信息变更，在核对完整差异后同步文档、契约和快照。不得自动重录整个快照、删除断言、跳过或弱化测试来制造通过。

在仓库根目录执行与 CI 一致的检查：

```zsh
export UV_CACHE_DIR="$PWD/.cache/uv"
uv sync --locked --group dev --extra ocr-cpu
uv run --locked ruff check app tests scripts
uv run --locked ruff format --check app tests scripts
uv run --locked pyright
uv run --locked python -m scripts.docs.check_openapi
uv run --locked pytest -v --cov=app --cov-fail-under=85
```

`pyright` 当前只检查 `app/api`、`app/schemas` 和配置层；扩展 `include` 前先修复目标目录的存量错误，不用批量 `ignore` 换取通过。覆盖率门槛当前为 85%，低于基线约 90%；新增核心逻辑应同步补测试。

OCR 运行时由互斥 extra 选择：`ocr-cpu`（`onnxruntime==1.31.1`）或 `ocr-gpu`（`onnxruntime-gpu==1.24.4`），两者不能同时启用；单独 `uv sync` 不会安装 ONNX Runtime，并会移除已装的那一个。`uv run` 不会移除已安装的 extra 包，但重新同步环境时仍须带上对应 extra。

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

## 七、代码工程规范

本节约束所有新增、修改和重构的代码。接口契约、目录职责和资源生命周期已在前面各节规定，本节不重复。

### 7.1 命名

- Python 遵循 PEP 8：模块/函数/变量 `snake_case`，类 `PascalCase`，常量 `UPPER_SNAKE_CASE`，内部实现前缀 `_`。
- 名称必须表达业务含义或技术职责；禁止 `data`、`temp`、`result`、`value`、`obj` 等无上下文名称。外部协议字段（如响应中的 `data`）和算法惯用名不受此限。
- 同一业务概念全仓库使用同一术语，不在不同模块给同一概念换名。
- 标识符禁止拼音和中英文混杂；已对外暴露的既有业务编码除外（如 `jianbiao`、`JLB13`、`fld_*`）。新增例外先登记到本节术语表，不得自行改名。
- 缩写仅使用广泛认可的技术缩写（`ocr`、`pdf`、`xlsx`、`wbs`、`cv`）或既有业务编码。

### 7.2 配置与常量

- 跨环境、跨部署变化的值只放在 `Settings`，并按现有规则同步 `Settings`、`.env.example` 和 README。
- 业务策略值（如意图置信度、澄清轮数、超时）放在使用处附近的模块级具名常量并注释来源；算法阈值就近具名。
- 禁止魔法数字和裸字符串字面量（如 `0.6`、`2400`、`3600`）；先命名，再在使用处引用。
- 禁止在 `app/` 业务代码中硬编码服务地址、端口、模型路径和密钥。
- 脚本复用 `Settings` 或显式 CLI 参数，不自行用 `os.environ.get` 定义第二套业务配置。
- 大量业务参数使用 Pydantic 模型或具名参数，不用不透明 `dict` 传递。
- 配置项、环境变量和 `Settings` 字段同名同义，不出现别名。

### 7.3 状态与并发

- 模块级只允许不可变常量或只读映射；业务数据、会话和运行状态禁止放在模块级可变对象中。
- 共享状态统一由 `lifespan` / `app.state` 管理，不通过修改其他模块的全局变量传值。
- 请求之间的消息、动态 Schema、缓存和执行状态必须隔离，不修改共享 Agent 实例。
- 新增长生命周期资源必须说明所有权、初始化、并发访问和释放方式，并在 `try/finally` 中释放。

### 7.4 函数与类

- 一个函数一个主要职责；建议不超过 60 行、嵌套不超过 3 层。超限先拆分，但不按行数机械拆分。
- 使用提前返回降低嵌套；禁止可变对象作为默认参数。
- 不隐式修改调用方入参或返回共享可变对象，除非函数契约明确说明。
- 位置参数超过 4 个或存在大量同类型参数时，使用具名参数或 Pydantic 模型。
- 仅在需要共享状态、封装行为或实现接口时使用类；不为形式引入 Service/Repository 层。
- 复杂函数在 docstring 中写明输入、输出、异常行为和副作用。

### 7.5 类型与数据结构

- 新增或修改的公共函数必须写参数和返回值注解；私有 helper 至少写返回值注解。
- 业务数据禁止裸 `dict[str, Any]`；`Any` 仅用于 LangChain state、第三方无类型返回值等外部边界。
- 同一数据在模块间传递时复用 `app/schemas/` 的模型或既有类型定义，不重复定义平行结构。
- 明确区分必填、可选（`| None`）和默认值；外部输入必须经 Pydantic 或显式校验。
- `pyright` 当前检查 `app/api`、`app/schemas` 和配置层；扩展 `include` 前先修复该目录的存量错误，不通过批量 `ignore` 换取通过。

### 7.6 异常与日志

- 禁止无理由捕获后忽略。`except Exception` 只允许出现在系统边界（模型/OCR 引擎、依赖自检、单条公式容错），且必须做以下三者之一：记录日志、写入错误结果、转换为项目异常。
- 转换异常保留原因：`raise ... from exc`；不得用伪造成功结果掩盖错误。
- 业务层抛 `app/errors.py` 中的异常；HTTP 映射只放在 `app/http_errors.py` 和领域 Router，业务层不抛 `HTTPException`。
- 使用 `logging.getLogger(__name__)`；业务路径禁止 `print`。仅 `if __name__ == "__main__"` 自检和 `scripts/` CLI 可以输出。
- 日志应包含操作和失败对象；不得输出密钥、完整输入、身份、历史或上游错误正文。

### 7.7 复用与注释

- 相同逻辑出现两次以上再抽公共函数，抽到 `app/ocr/core/` 等既有公共层，不新建平行的工具模块。
- 注释解释原因、约束和非直观逻辑，不复述代码；修改行为时同步更新注释和文档。
- 删除确认无用的代码；不擅自删除仍可能被外部调用的公共接口。

### 7.8 存量代码与变更边界

- 新增代码遵守本节；修改旧代码时只在触及范围内改善，不借机大规模重构。
- 规范与既有设计冲突时先报告，由用户决定是否调整；不得以规范化为由改变业务逻辑、接口契约或数据结构。
- 涉及公共 API、配置结构或数据模型兼容性变更时，先说明影响并取得用户确认，按第四节执行。

## 八、配置、依赖与运维

- 项目固定 Python 3.12；Ruff 负责基础 lint、导入排序和格式；命名、类型与代码风格按第七节执行，不为本次任务无关的风格批量重写。
- 注释和 docstring 统一使用中文；标识符、命令、路径、环境变量和必要技术术语保留原文。新增或修改代码时保持该风格，翻译注释不得改变代码行为。
- 依赖通过 `uv add` 管理，`pyproject.toml` 和 `uv.lock` 一起更新，禁止手改锁文件。固定已验证的 `langchain`、`langchain-core`、`langchain-openai`；升级前查官方文档与 provider 兼容性，不引入不必要框架。
- OCR 的 ONNX Runtime 只通过互斥 extra 安装：`ocr-cpu`（CPU 版 `onnxruntime`）或 `ocr-gpu`（`onnxruntime-gpu`）。两者提供同名 `onnxruntime` 模块，不得同时装入同一环境；新增部署入口须显式指定其中一个 extra。
- `Settings` 的读取顺序为 API 进程环境、根目录 `.env`、源码默认值；新增配置同步更新 `Settings`、`.env.example` 和 README，保留本机 `.env`。
- launchd 启动的后台任务不保证继承当前终端临时导出的所有变量。持久业务配置优先维护根目录 `.env`，不要声称 `export LLM_*` 或 `OLLAMA_*` 一定传入后台任务；Ollama 自身配置需由其实际启动环境提供。
- `LANGSMITH_TRACING=false` 为默认值，只有显式配置才启用；凭据运行时注入，不记录或提交真实业务 traces。`SecretStr` 不替代日志、错误和提交内容的脱敏。
- 使用 `scripts/dev/services.sh` 管理本项目 Mac 任务；不停止其他方式启动的进程，不编辑 shell profile。
- 日志在 `.logs/`，模型由 Ollama 或独立 vLLM 环境管理；密钥和私有证书在受控运行环境或 `.secrets/`，不写入业务代码、命令输出或仓库。
- 主应用的用户/会话 ID 不提供权限保护；生产暴露或外部动作的权限设计应单独明确。

## 九、Git 与交付要求

- 保持 `origin` 为 `https://github.com/TonyZhang128/agent-dev.git`，尊重现有分支、历史和用户修改。不执行破坏性清理、强制推送或覆盖式回退。
- 提交前检查 `git diff --check`、暂存 diff 和状态，只提交本任务文件/修改块；避免在脏工作区直接 `git add .` 或批量暂存整个目录。
- 排除 `.env`、`.secrets/`、模型、`.venv/`、缓存、日志、验收输出及本地 `skills/`；已有未跟踪目录不因本任务自动纳入提交。
- `README.md` 面向使用和开发，`AGENTS.md` 维护共享规则，`docs/` 保存详细契约及专题说明；更新时核对实际脚本和目录，避免重复维护相互矛盾的规则。
- 包版本以 `pyproject.toml` 为准，OpenAPI 标题/版本以 `FastAPI(...)` 为准。二者分别维护，当前数值均为 `0.1.0`，但含义不同；不要擅自统一，修改时说明含义并按第四节处理正式契约、草案和契约快照。
- 交付简要说明修改文件、原因、实际执行的检查、已有失败/未验证风险、启动方法及项目路径。未执行的测试、真实模型验证、部署或 Linux GPU 验收不得宣称通过。

## 十、可选本地技能

对应文件存在时，相关工作先阅读并遵循；本地 `skills/` 已被 Git 忽略，干净克隆不要求存在。

| 工作类型 | 文件 |
| --- | --- |
| LangChain Agent、工具、结构化输出 | `skills/langchain-fundamentals/SKILL.md` |
| LangChain 依赖调整 | `skills/langchain-dependencies/SKILL.md` |
| 检索与知识库 | `skills/langchain-rag/SKILL.md` |
| LangGraph 状态和工作流 | `skills/langgraph-fundamentals/SKILL.md` |

来源：<https://github.com/langchain-ai/langchain-skills>，固定修订 `16a992f09ab3ccfb642dd4f08d350d833d1990bf`。使用仓库本地 `skills/`，不要求写入受保护的 `.agents/` 或 `.codex/`；用户明确指令和仓库实际约束优先。
