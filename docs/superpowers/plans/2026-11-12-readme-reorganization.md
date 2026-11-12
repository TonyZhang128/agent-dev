# README 与维护文档重组计划

> **For agentic workers:** 使用 superpowers:executing-plans 按任务顺序执行。

**Goal:** 面向项目开发维护人员精简 README，将有效维护信息迁入专题文档。

**Architecture:** 首页提供项目总览、最短启动路径与文档入口；专题负责完整操作说明，接口继续由 interfaces/ 管理。

**Tech Stack:** Markdown；以 Python 3.12 项目的源码、配置、脚本和 CI 核对内容。

**Spec:** 本次对话已确认的七节 README、四篇维护文档及 docs/README.md 索引方案。

## Global Constraints

- 仅修改文档，不改变代码、配置、接口、依赖或用户数据，不重启服务。
- 复用已有接口、OCR、部署及验收专题，不重复维护契约。
- 不将历史验收结果描述为当前部署状态；不提交、不推送。

## Review Focus

- 启动步骤区分首次下载模型与已有环境；保留 .env。
- 迁移配置表与 Settings 对齐，避免复制真实凭据。
- 区分 Agent、OCR、静态诊断和真实依赖验收。
- 更新旧 README 锚点引用；检查新增相对链接和命令入口。
- 规则在 AGENTS.md、契约在 interfaces/，不产生第二份权威来源。

## Tasks

- [x] 核对现有 README、专题、源码、脚本、配置与 CI。
- [x] 重写 README，新增 local-development、configuration、architecture、testing 四篇文档。
- [x] 新增 docs/README.md，修复脚本/API/部署文档中的相关导航。
- [x] 检查本次文档链接、配置覆盖、命令路径、完整 diff 与 git diff --check；记录结果。

纯文档变更不添加行为测试、不运行真实推理；使用文档静态检查和逐项核对验收。

## 验证结果

- README 从 442 行精简为 127 行；四篇维护专题与完整文档索引已建立。
- 10 篇变更文档的 105 个本地链接／锚点、代码围栏及 46 个脚本／模块命令入口检查通过。
- 26 个 Settings 字段覆盖与默认值经 AST 逐项比对通过，未加载实际环境或密钥。
- 全仓库已跟踪 Markdown 中指向根 README 的旧锚点引用检查通过。
- 独立只读审查未发现阻断问题或需修正的事实错误。
- 未修改代码、接口、依赖和实际配置，未启动服务、安装依赖或运行真实推理；未提交或推送。
