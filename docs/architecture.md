# 架构与扩展

本项目作为公路工程业务系统的算法层，以同一 FastAPI 应用提供智能体和 OCR 服务。应用入口为 `app.main:app`，默认监听 `127.0.0.1:8309`；运行配置见 [配置说明](configuration.md)。

## 1、请求链路

```text
业务系统 → FastAPI → 领域 Router
                       ├── Agent → runtime → ChatOpenAI → Ollama / vLLM
                       └── journal → 表格定位与对齐 → 整页 OCR → 字段提取
                                                              └── mainWork 规则 / Agent
```

LLM 是独立模型推理服务；OCR 引擎在算法服务进程内运行。可选云端回退沿用统一 Agent 运行时，触发与预算见 [配置说明](configuration.md#4云端回退)。当前没有数据库、服务端持久会话或业务系统写入工具。

## 2、模块职责

| 位置 | 职责 |
| --- | --- |
| `app/main.py` | 应用工厂 `create_app()`、lifespan、共享资源初始化与释放、异常处理注册 |
| `app/api/router.py` | 统一聚合领域 Router，每个领域注册一次 |
| `app/api/agents.py` | 日志、业务端／归档端意图、聊天 HTTP 入口 |
| `app/api/ocr.py`、`system.py` | 新版监理日记识别；存活、就绪和静态依赖诊断 |
| `app/schemas/` | Pydantic 请求响应模型、严格输入及跨字段校验 |
| `app/agents/base.py` | 共享 `BaseAgent` 和 `StructuredAgent` |
| `app/agents/runtime.py`、`middleware.py` | 统一构建／执行 Agent、输出检查、超时、步数与可选回退 |
| `app/agents/history.py` | 请求局部历史、上下文预算与完整回合裁剪 |
| `app/agents/intent_business.py`、`clarify.py` | 层级意图、目录校验和澄清流程 |
| `app/agents/profiles.py`、`intent.py` | 归档端扁平意图配置及处理 |
| `app/resources/intent/`、`intent_catalog.py` | 业务目录源 JSON、生成枚举和运行时只读目录视图 |
| `app/prompts/` | 通过 `load_prompt()` 加载各能力的系统提示词 |
| `app/llm.py` | 模型工厂、HTTP 客户端所有权和模型列表就绪检查 |
| `app/ocr/core/` | 应用级 OCR 资源、依赖诊断、CUDA 运行库和引擎 |
| `app/ocr/journal/` | 模板、照片预处理、表格定位与对齐、字段匹配、输出及 mainWork 编排 |
| `app/errors.py`、`app/http_errors.py` | 非 HTTP 异常；统一 HTTP 映射和脱敏 |

依赖方向为 `main → 路由聚合 → 领域 Router → Schema／业务资源`。Router 不导入全局 `app`；业务层不依赖 FastAPI 请求与响应对象，不为目录形式增加只做转发的 Service／Repository。

## 3、资源生命周期与隔离

模型推理服务、各 Agent 和 `OCRResources` 由 lifespan 创建，保存在当前应用 `app.state`，Router 从当前请求取得。业务端意图共享当前应用的 ChatAgent 和 ClarificationAgent。OCR 模型、模板与引擎按需加载；OCR 推理加锁，同步识别在线程池执行。

lifespan 使用 `@asynccontextmanager`，异步生成器类型为 `AsyncGenerator[None, None]`，通过 `try/finally` 清理资源；模型推理服务拥有同步、异步 HTTP 客户端，包括注入的客户端。每个应用／worker 独立持有资源，不跨应用共享缓存，也不按请求重复构建昂贵资源。

已编译 Agent 可复用，但消息、动态 Schema 和执行状态必须请求隔离，不修改共享 Agent。运行时不启用 checkpointer；历史由调用方完整传入并按预算裁剪，身份只通过请求局部 metadata 传递，见 [会话说明](sessions.md)。

## 4、智能体实现

所有推理经 `build_agent()`／`invoke_agent()`，由 `langchain.agents.create_agent()` 执行，不直接调用 SDK 建立旁路。

- `BaseAgent[请求, 结果]` 统一提示词加载、构建和调用；子类实现 `name`、`messages()`、`parse_result()`。
- `StructuredAgent[请求, 结果]` 补充 Schema 与 Pydantic 校验；业务类实现 `name`、`result_type`、`user_content()`。
- 主模型使用 `ProviderStrategy(schema, strict=True)`；提供方输出后仍需业务校验。回退模型兼容处理见配置文档。

业务端页面／功能编码唯一源为 `app/resources/intent/business_pages.json`。修改后运行生成器，运行时不读取源 JSON：

```zsh
uv run --locked python -m scripts.intent.compile_catalog
uv run --locked python -m scripts.intent.compile_catalog --check
```

归档端维持独立 `IntentProfile`，新增同类 profile 时复用 `profiles.py` 和 `intent.py`。目录／提示词修改后重启算法服务以刷新资源；涉及对外编码或行为变更时先走契约流程。

## 5、OCR 与 mainWork

当前 OCR HTTP 入口仅为 `/ocr/daily-logs-new`，不将已移除的旧照片、简表、填表和 WBS 接口列为可用能力。识别过程使用随代码发布的 journal 模板，定位与对齐后整页 OCR，再匹配业务栏目。

mainWork 优先按可靠的施工、旁站、巡视标题提取，规则不足时交给 MainWorkAgent 基于完整原文生成三个字段，再检查关键数据。生成有独立的总预算和并发限制，失败时返回受控错误，不能伪造成功或改变事实。

模板构建与照片诊断见 [模板识别](journal-template-recognition.md)，mainWork 实现见 [处理专题](journal-mainwork-split.md)，对外行为以 [接口说明](../interfaces/journal/main-work-processing.md) 为准。

工作区未跟踪的独立 `ocr/` 若存在，不属于主应用；修改前阅读其自身 README，不合并依赖或路由。docsvc 迁移属于历史背景，当前能力以源码和接口清单为准。

## 6、扩展流程

1. 明确业务需求和验收标准，检查 [接口文档](../interfaces/README.md)。新增／变更对外行为先提交草案，由用户确认契约后再实现。
2. 根据已确认行为定义正常、边界和失败用例，先写能复现缺失行为的测试；纯文档或类型调整按实际影响验证。
3. 在 `app/schemas/` 定义模型，在 `app/prompts/` 添加提示词，在 `app/agents/` 继承合适基类，复用统一运行时。
4. 在 lifespan 创建共享实例，由领域 Router 获取；新增领域使用 `APIRouter`，在 `app/api/router.py` 聚合，避免重复前缀和注册。
5. 完成离线、契约、隔离和必要真实依赖验收，同步接口与专题文档，见 [测试与验收](testing.md)。

工具通过 LangChain `@tool` 定义并传入 `build_agent(..., tools=...)`，保留统一输出检查、总超时和步数控制。接入外部写操作前须明确身份、权限、幂等和业务确认；当前生成能力不代表有权执行业务动作。详细工程规范统一见 [AGENTS.md](../AGENTS.md)。

## 7、参考资料

- [LangChain Agents](https://docs.langchain.com/oss/python/langchain/agents)
- [LangChain 结构化输出](https://docs.langchain.com/oss/python/langchain/structured-output)
- [ChatOpenAI](https://docs.langchain.com/oss/python/integrations/chat/openai)
- [Ollama OpenAI 兼容接口](https://docs.ollama.com/api/openai-compatibility)
- [Ollama 结构化输出](https://docs.ollama.com/capabilities/structured-outputs)
