# 监理日记与本地诊断接口

当前仅保留 `POST /ocr/daily-logs-new` 和系统级 `GET /diagnostics`。字段以 [OpenAPI草案](../drafts/fastapi.openapi.json) 为准；已确认成功结构和表格失败响应分别见 [成功子契约](../journal/response.schema.json)、[无表格子契约](../journal/table-not-found.schema.json)。完整OpenAPI仍为待确认，不能据此扩展接口。

## 1、图片输入与处理

- `path`、`img`至少一个非空；同时提供时img优先。img支持base64及data URI。
- path必须是PROJECTS_ROOT内文件，兼容projects/前缀；拒绝绝对路径、穿越及越界符号链接。
- taskId去除首尾空白后回显，缺省为null；不生成服务端任务。
- 定位阶段只接受通过模板行列/合并结构核验的真实table。字段及标签以table为坐标基准，包含表外项目名称、编号、审核人。
- 成功定位后整图一次OCR；字段名漏识别不妨碍可靠几何定位。文字框不强行跨栏分配，缺失不补写。
- mainWork先合并OCR文本，按施工情况、旁站情况、巡视情况关键词规则提取；不足时Agent基于全文生成三个字段。允许整理表达、合并断句、去标题，保留全部事实和关键数据，不摘要不补充；没有对应内容为null。失败保持502。正式语义见 [mainWork处理](../journal/main-work-processing.md)。

## 2、响应与失败

成功严格为 `{"status":200,"message":"识别完成","data":...}`，data包含taskId、documentType、common、fields。只有真实合法空白表格可以成功返回空字段，不能把定位失败包装为空值200。

| HTTP | 场景 |
| --- | --- |
| 400 | 无通过结构核验的table或候选歧义：固定detail为“未检测到监理日志表格，请重新拍摄”，在OCR前终止；其他既有400仍包括非法路径、无法解码及文档处理错误 |
| 422 | 请求字段校验失败，包括path/img均为空 |
| 502 | mainWork无法可靠拆分，保持既有固定detail |
| 503 | OCR模型不可用等既有资源失败 |

错误响应统一detail，不回显原始图片、OCR正文、密钥或上游正文。成功子Schema不增加诊断字段；逐线支持率、来源覆盖mask、定位图仅在内部和本地工具中使用。HTTP200、非空数量和OCR置信度不是准确率保证。

## 3、同步、重试与副作用

一次HTTP请求完成全部处理。CPU/OCR在线程池中执行，共享引擎按应用串行加锁；mainWork模型按已有并发和超时控制。没有异步任务、轮询、webhook、持久会话或multipart上传。

接口只读图片，不写PDF/Excel、模板或固定示例JSON，可以重试；结果仍可能随模型、照片质量、模板版本变化。当前接口没有自定义鉴权，需在既有可信部署边界内使用。

## 4、GET /diagnostics

保留现有静态诊断字段：依赖、运行库、设备provider、模型目录、资料库与数据池。不会初始化OCR引擎、注册CUDA、执行推理、访问网络或写文件；ok=false仍为HTTP200。旧资料库检查项仍属于此存量接口，本次未改变其字段或判定语义，且不参与journal模板匹配。

实现与部署见 [OCR说明](../../docs/ocr.md)，算法及真实验收见 [table模板识别](../../docs/journal-template-recognition.md)。
