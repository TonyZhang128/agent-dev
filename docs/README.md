# 文档索引

[项目 README](../README.md) 提供总览与快速开始；本文按开发维护任务组织详细资料。对外接口统一从 [interfaces/README.md](../interfaces/README.md) 进入，开发与 AI 协作规则统一见 [AGENTS.md](../AGENTS.md)。

## 开发维护

| 任务 | 文档 |
| --- | --- |
| 安装依赖、启动服务、断点调试、代理排障 | [本地开发](local-development.md) |
| 修改模型、云端回退、上下文、OCR 设备与路径 | [配置说明](configuration.md) |
| 理解分层、生命周期、目录生成与扩展流程 | [架构与扩展](architecture.md) |
| 离线检查、契约快照、真实依赖和部署验收 | [测试与验收](testing.md) |
| 查找开发、生产、模型与验收脚本 | [脚本索引](../scripts/README.md) |
| 了解本地业务样本 | [数据说明](../data/README.md) |

## 接口与智能体

| 任务 | 文档 |
| --- | --- |
| 查询接口、正式契约／草案与评审流程 | [接口索引](../interfaces/README.md) |
| 查看智能体 HTTP 约定和调用示例 | [智能体 API](agents-api.md) |
| 理解用户、会话历史与预算裁剪 | [用户与会话](sessions.md) |
| 检查日志事实、数值单位和真实模型效果 | [日志总结验收](log-summary-testing.md) |
| 检查业务意图、澄清和评测集 | [意图识别验收](intent-testing.md) |

## OCR 算法与模板

| 任务 | 文档 |
| --- | --- |
| 了解当前 OCR 能力、资源路径与静态诊断 | [OCR 说明](ocr.md) |
| 构建模板、检查表格对齐、字段提取与真实照片效果 | [监理日记模板识别](journal-template-recognition.md) |
| 维护 mainWork 关键词提取、全文生成与关键数据校验 | [mainWork 实现](journal-mainwork-split.md) |
| 查询 mainWork 已确认的对外处理语义 | [mainWork 接口说明](../interfaces/journal/main-work-processing.md) |

## 生产部署

- [Docker 生产部署](docker.md)：权重准备与迁移、镜像构建、Compose、GPU OCR 和分别验收。
- [Linux 非容器部署](deployment-linux.md)：独立 vLLM 环境、API 启动、systemd 与真实验收。

## 历史记录与实施计划

以下资料用于追溯当时决策与检查，不代表当前接口能力、代码状态或部署已通过验收。日常操作优先使用上述维护文档。

- [APIRouter 审查记录（2026-10-31）](apirouter-review-2026-10-31.md)
- [docsvc 迁移记录（2026-10-31）](docsvc-integration-2026-10-31.md)
- [代码审查记录（2026-10-31）](code-review-2026-10-31.md)
- [设计与实施计划目录](superpowers/)
