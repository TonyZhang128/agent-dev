# APIRouter 模块化实施计划

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task. 当前用户已明确要求在当前目录直接实施；保留现有未提交修改，不创建 worktree、不提交。

**Goal:** 将主应用六个接口迁移到 APIRouter，保持完整 HTTP 契约及生命周期。

**Architecture:** 新建 `app/api/{router,agents,business,system}.py`，只拆 HTTP 层。`main.py` 保留工厂、资源初始化和清理、异常处理注册及一次 `include_router()`。现有 `app/agents/` 作为业务层，复用 `schemas.py`、`config.py`、`llm.py`，不新增转发 Service。

**Tech Stack:** 现有 Python 3.12、FastAPI 0.136.3、Pydantic；不修改依赖。

**Spec:** 用户本轮完整需求及仓库 `AGENTS.md`。

## 全局约束和范围

- `agents.router` 使用 `/api/agents`、`["智能体"]`；`business.router` 使用 `/api/business`、`["业务规划"]`。
- `system.router` 保留 `/health`、`/ready`，不新增 tags，以保持原 OpenAPI。
- 保留函数名、装饰器参数、默认状态码和所有 `async`/`await`；保留六个 operationId。
- 保留 `request.app.state` 资源取得方式及启动/关闭时机；无每请求构造，无隐式跨应用资源。
- 无 Query/Path/Header 参数、无自定义鉴权/依赖/中间件；保持现状。
- `ocr/` 是未跟踪的独立服务，非 `app.main:app` 的注册模块；本轮不迁移或挂载。
- 探索过单文件 Router、每接口独立文件与按领域拆分：采用三个领域模块，控制文件层级与样板代码。

## Review Focus

- 路径前缀重复、路由遗漏或重复：完整 OpenAPI 比较、独立挂载聚合 Router 验证。
- operationId、tags、响应模型及参数变化：固定重构前完整 OpenAPI fixture。
- `/ready` 错误与 `/health` 上游无关性：HTTP 故障/无模型/非法模型列表测试。
- 多应用资源串用或重复初始化：两应用、多请求检查真实资源身份与模型返回。
- 启动失败或取消时资源泄漏：复用现有生命周期测试，不修改初始化流程。

## Task 1: 契约保护和路由迁移

**Files:** 新建 `app/api/__init__.py`、`router.py`、`agents.py`、`business.py`、`system.py`；修改 `app/main.py`；新建 `tests/test_routing.py`、`tests/fixtures/api-openapi.json`。

**Interfaces:** 每个模块导出 `router: APIRouter`，聚合模块导出 `api_router: APIRouter`；`create_app(service: ModelService | None = None) -> FastAPI` 保持不变。

- [x] 保存当前完整 OpenAPI，记录六个接口和资源行为；执行现有测试作为基线。
- [x] 先增加 OpenAPI 特征测试、聚合 Router 可独立挂载测试、资源隔离及 readiness 测试。
- [x] 运行新测试：现有行为测试通过，聚合挂载测试因 `app.api.router` 缺失失败（RED）。
- [x] 迁移六个原函数，按原注册顺序聚合；主应用调用 `include_router(api_router)`。
- [x] 运行新增测试、原 HTTP/生命周期/会话测试，确认 GREEN。

## Task 2: 文档、完整验证和审查

**Files:** 修改 `README.md`、`docs/agents-api.md`；新增 `docs/apirouter-review-2026-10-31.md`。

- [x] 更新目录、新增 Agent 的注册步骤，记录接口参数、返回、异常及迁移对应关系。
- [x] 运行锁定依赖同步、Ruff lint/format、全部 pytest 和 AGENTS 中两个不存在目录的命令，分别记录结果。
- [x] 比较完整 OpenAPI、注册数量、导入依赖；审查最小 diff、资源所有权、错误处理及同步语义。
- [x] 尝试用仓库脚本重启主 API；若端口由外部进程占用，保留它，使用隔离回环端口验证新应用启动和健康检查。
- [x] 报告实测结果、部署状态及独立 OCR/Linux 范围；纯路由搬迁不改变推理协议，不强制重复完整真实模型评测。

## 执行记录

- 已确认工作区存在前序修改，所有迁移基于当前文件而非 HEAD；原有审查记录保持原样。
- Task 1: 基线 253 通过；新增测试 1 RED/9 通过；迁移后针对性 164 通过。
- Task 2: 完整 263 通过，Ruff lint/49 文件 format 通过；OpenAPI 相同，6 个唯一异步路由，22 个模块无导入环。
- 运行验证：端口 8000 外部进程保留；正规提权后临时回环 API 启动、健康、就绪、OpenAPI、四个 422 及真实聊天通过，临时进程已停止。
- 范围决定：不改独立未跟踪 OCR 服务、不升级依赖、不重写业务层；完整真实业务评测与 Linux 部署未执行。
- Final review: 独立只读代码复审无阻断发现；复审者另运行 25 项针对性测试通过。文档已补齐主执行者实际全套/运行结果，未将针对性测试作为部署证据。
