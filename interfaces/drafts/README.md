# 接口草案与评审

## 1、当前状态

用户于 2026-11-12 明确批准 `GET /diagnostics` 完整契约，以及当前 10 个操作的完整 OpenAPI 基线。
正式文件为 [../openapi/fastapi.openapi.json](../openapi/fastapi.openapi.json)，契约版本为 `0.1.0`。
合并 YJH 后，`POST /ocr/jianbiao` 是唯一待确认操作；用户明确选择暂不批准，保留草案。
合并实现共有 11 个操作，正式基线仍为 10 个，严格契约校验会报告这一差异；未修改或弱化校验。
完整待确认视图见 [API.md](API.md)，已删除的其他旧 OCR/WBS 接口不在批准范围。

原 `0.1.0-review.2` 已完成评审。曾列出的 9 个待确认操作和 15 个操作统计已经过时，
不作为现有接口清单或恢复旧路由的授权。当前清单见 [接口索引](../README.md#5接口清单)。

## 2、草案的用途

[fastapi.openapi.json](fastapi.openapi.json) 仍为从当前实现导出的草案，整包状态保持
`draft-pending-review`；其中已有正式批准依据的 10 个操作为 `confirmed`，简表操作为 `pending-review`。
未来新增或变更的内容必须重新评审，不能因现有基线获批而自动视为批准。

```zsh
uv run --locked python -m scripts.docs.export_openapi
uv run --locked python -m scripts.docs.check_openapi
```

导出只写入本目录，禁止写入 `interfaces/openapi/`。校验默认以完整正式契约为准，
不覆盖正式文件；`interfaces/API.md` 默认从正式契约生成。

## 3、后续变更流程

1. 在本目录提交 `pending-review` 草案，说明路径、方法、请求、响应、错误及兼容性差异。
2. 用户明确批准后，人工更新正式契约和 [CHANGELOG](../CHANGELOG.md)。
3. 再修改实现与调用方，执行契约校验和测试。

用户未回复或仅要求继续开发不代表批准。历史监理日记方案仍保留在本目录，
当前行为以正式契约为准。
