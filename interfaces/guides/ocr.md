# 监理日记、简表与本地诊断接口

当前提供三个监理日记入口，以及系统级 `GET /diagnostics`。监理日记字段和行为以 [正式子契约](../openapi/journal.openapi.json) 及 [三入口语义](../journal/capabilities.md) 为准，既有 10 个操作已纳入正式基线；本次合并的简表接口仍为待确认草案。

| 入口 | 输入 | 输出 |
| --- | --- | --- |
| `POST /ocr/journal` | path/img、可选 taskId | 内部串联识别与生成，输出完整业务结果 |
| `POST /ocr/journal/recognize` | 同上 | 全部文字框、四点原图坐标、置信度、11 个拆分前栏目 |
| `POST /ocr/journal/process` | recognize 响应的完整 data | 完整业务结果，与 journal 格式一致 |

旧 `/ocr/daily-logs-new` 已删除，不重定向；调用方必须更新路径。

## 1、图片输入与处理

- `path`、`img`至少一个非空；同时提供时img优先。img支持base64及data URI。
- path必须是PROJECTS_ROOT内文件，兼容projects/前缀；拒绝绝对路径、穿越及越界符号链接。
- taskId在 recognize 结果中去除首尾空白后回显，缺省为null；最终业务格式不包含它；不生成服务端任务。
- 定位阶段只接受通过模板行列/合并结构核验的真实table。字段及标签以table为坐标基准，包含表外项目名称、编号、审核人。
- 成功定位后整图一次OCR；字段名漏识别不妨碍可靠几何定位。文字框不强行跨栏分配，缺失不补写。
- 工作原文由 JournalAgent 生成施工、巡视四项和旁站五项；允许基于原文补全表达，不编造事实或数据，无依据的子项为 null。正式语义见 [工作内容生成](../journal/main-work-processing.md)。

## 2、响应与失败

组合和业务生成入口成功严格为 `{"code":200,"message":"success","data":{"jsonData":...}}`，jsonData 包含 common 和 fields。只有真实合法空白表格可以成功返回空字段，不能把定位失败包装为空值200。

| HTTP | 场景 |
| --- | --- |
| 400 | 无通过结构核验的table或候选歧义：固定detail为“未检测到监理日志表格，请重新拍摄”，在OCR前终止；其他既有400仍包括非法路径、无法解码及文档处理错误 |
| 422 | 请求字段校验失败，包括path/img均为空 |
| 502 | mainWork无法可靠拆分，保持既有固定detail |
| 503 | OCR模型不可用等既有资源失败 |

纯 OCR 使用 `status/message/data` 包装，data 结构保持原契约；不调用语言模型。process 接收这个 data，返回最终业务格式，不读取图片；请求无效 422，生成失败 502。

错误响应统一detail，不回显原始图片、OCR正文、密钥或上游正文。组合成功子Schema不增加诊断字段；纯 OCR 新增公开识别明细，逐线支持率、来源覆盖mask、定位图仅在内部和本地工具中使用。HTTP200、非空数量和OCR置信度不是准确率保证。

## 3、同步、重试与副作用

一次HTTP请求完成全部处理。CPU/OCR在线程池中执行，共享引擎按应用串行加锁；mainWork模型按已有并发和超时控制。没有异步任务、轮询、webhook、持久会话或multipart上传。

监理日记接口只读图片，不写PDF/Excel、模板或固定示例JSON，可以重试；结果仍可能随模型、照片质量、模板版本变化。当前接口没有自定义鉴权，需在既有可信部署边界内使用。

## 4、GET /diagnostics

保留现有静态诊断字段：依赖、运行库、设备provider、模型目录、资料库与数据池。不会初始化OCR引擎、注册CUDA、执行推理、访问网络或写文件；ok=false仍为HTTP200。旧资料库检查项仍属于此存量接口，本次未改变其字段或判定语义，且不参与journal模板匹配。

实现与部署见 [OCR说明](../../docs/ocr.md)，算法及真实验收见 [table模板识别](../../docs/journal-template-recognition.md)。

## 5、POST /ocr/jianbiao（待确认）

- 请求在 `path`/`img` 之外必填 `form`（简表模板 ID 或兼容别名，如 `subgrade_spot_check`、`JB12-4.5.2-4`）；`cfg`、`bound` 为预留字段，当前版本不使用。
- 识别链：模板行列结构核验（0°/90°/180°/270°）→ 透视校正 → 单次整页 OCR → 字段归属；检测失败不退回整图 OCR，也不做逐格重识。
- 成功 `data` 固定含 `taskId`、`documentType`、`common`（5 个公共字段）和 `fields.records`（固定 10 行）；空字段、歧义字段和无法完整解析的合格率为 `null`，不补写示例值。
- `out` 非空时为数据池内输出目录，写出 `response.json`、`diagnostics.json`、`aligned.png`；空则不写文件。路径越界返回 400。
- 失败语义：400（非法路径、图片无法解码、模板未配置、未检测到通过模板结构核验的简表表格，固定 detail“未检测到简表表格，请重新拍摄”）、422（请求校验失败）、503（OCR 模型不可用）。不调用语言模型。
