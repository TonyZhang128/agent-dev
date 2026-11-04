# 文档加工接口说明

本文说明 `/diagnostics`、`/ocr/*`、`/wbs/draft` 的业务流程、数据池约束、输出副作用和错误
处理。字段结构以 [OpenAPI 草案](../drafts/fastapi.openapi.json) 为准；实现细节、模板目录、
OCR 模型和辅助脚本见 [文档加工与 OCR](../../docs/ocr.md)。

## 共同规则

- 全部为同步请求；CPU 处理在线程池执行，同一应用的 OCR 推理串行加锁。
- 没有任务 ID、异步轮询、webhook、回调、分页或 multipart 上传。
- 没有鉴权。应由可信调用方在既有部署边界内使用。
- 成功（PNG 除外）返回：

  ```json
  {"status": 200, "data": {}}
  ```

  `status` 是业务成功标记，与 HTTP 200 一致，不是 HTTP 状态码的替代。
- 识别、填表和 WBS 只产生草稿，不执行人工确认、审批或数据库写入。
- 模板和 OCR 引擎按需加载。应用启动不读取模板；缺模板只影响相关请求。
- 模板或 OCR 模型不可用返回 503，其他智能体接口继续可用。

## 数据池与路径

- `TEMPLATES_ROOT`、`ADMIN_ROOT`、`ASSET_ROOT`、`PROJECTS_ROOT` 由 Settings 配置，相对路径
  以仓库根目录解析。
- 输入 `path`、`out`、`drawings` 必须是 `PROJECTS_ROOT` 内的相对路径，可带或不带
  `projects/` 前缀。
- 拒绝绝对路径、目录穿越、越界符号链接和非文件输入；返回 400。
- `out` 为空不写文件。非空必须以 `.pdf` 结尾；Excel 和校正图分别为同名 `.xlsx`、
  `.warp.jpg`。
- 返回的 `pdf`、`xlsx` 相对 `PROJECTS_ROOT`。
- `drawings` 支持 PDF 文件或 `*_N.pdf` 单页拆分目录；目录内其他文件忽略，越界 PDF 返回 400。

## 图片输入

`POST /ocr/recognize` 和 `POST /ocr/daily-logs`：

- `path` 与 `img` 至少提供一个。
- `img` 为 base64 编码图片，兼容 `data:image/...;base64,` 前缀。
- 同时提供时优先使用 `img`。
- 两者都为空或只有空白返回 422。
- 图片无法解码、路径不存在或不是文件返回 400。

`POST /ocr/jianbiao` 只接受数据池照片 `path`，不接受 base64。

## 各接口流程

### `GET /diagnostics`

系统级本地诊断，不访问上游模型服务。检查 PyMuPDF、openpyxl、OpenCV、NumPy、RapidOCR、
ONNX Runtime 能否导入，`OCR_DEVICE` 与 onnxruntime provider 是否一致，以及 OCR 模板清单、
版面 JSON、WBS 规则、模型目录和数据池是否可用。`data.ok` 汇总必需检查，`data.warnings`
记录模型目录为空、表样目录缺失等非致命问题；`data.ok=false` 时仍返回 HTTP 200。

该接口不初始化 OCR 引擎、不加载模型、不注册 CUDA DLL、不访问网络、不写文件。“推理设备”
只证明 provider 可用，CUDA 真实初始化在首次 OCR 时验证；模型文件 sha256 由
`scripts.models.download_ocr_models --check` 校验。

### `POST /ocr/recognize`

1. 读取图片。
2. 普通 OCR 得到文字框。
3. 若提供 `form` 且模板存在，按栏目文字和模板坐标对齐。
4. 按栏目提取字段；无法对齐时只按栏目文字取值，并在 `warning` 提示核对表号。
5. 返回 `fields`、`keys`、`detail`、`lines`、`align`、`warning`、`image`、`ms`。

- 未知表号不报错，仍尝试按栏目文字取值。
- `align.how` 为 `anchors` 时才按模板坐标取值；`mismatch` 时不应信任坐标。
- 200 不代表每个字段准确，识别结果必须人工核对。

### `POST /ocr/daily-logs`

1. 寻找纸张/表格外框并透视校正。
2. 按 JLB13 固定栏目逐格 OCR。
3. 日期归一为 `yyyy-mm-dd`，长文本栏保留拼接结果。
4. 返回 `recognized`、`detail`、`frame`、`processed`、`warning`、`image`、`ms`。

- `processed` 是后处理占位，当前固定为 `{}`；调用方先使用 `recognized` 和 `detail`。
- `frame.how` 为 `whole` 时表示未找到外框，应按整张照片校正，需核对定位。
- 不写 PDF/Excel。

### `POST /ocr/jianbiao`

1. 按 `form` 找目标表的简表版面；没有简表版面返回 400。
2. 寻找外框、透视校正、逐格识别。
3. 将项目资料 `bound` 与照片识别值合并，照片手写值优先。
4. 按 `cfg` 的公式/引用计算目标表。
5. `out` 非空时写同名 PDF、Excel 和校正图。
6. 返回 `jianbiao`、`recognized`、`detail`、`frame`、`values`、`errors`、`anchors`、
   `pdf`、`xlsx`、`xlsxSkipped`、`ms`。

### `POST /ocr/fill`

不识别照片，只按 `cfg` 公式/引用计算 `values` 并回填目标表。

- 公式目标字段以计算结果为准，传入的旧值不算数。
- 单条公式失败进入 `errors`，该字段留空；调用方必须检查 `errors`。
- 循环引用返回 400。
- `out` 为空只计算，不写文件；非空时写 PDF/Excel。
- Excel 无对应格子或有冲突时，通过本次响应的 `xlsxSkipped` 返回，不使用共享状态。

### `GET /ocr/blank/{form}.png`

- 渲染模板表样第 1 页为 PNG。
- `width` 最小 1；实际渲染宽度不超过 2400，超过时按 2400 处理。
- 模板没有该表号的 PDF 返回 404。
- 响应是原始 `image/png`，带 `Cache-Control: max-age=3600`，不是 JSON 包装。

### `GET /ocr/sheet/{form}`

返回表样上可填的版面栏（`fld_*`）和其余空格子（`g*`）：

- `field`：字段 ID 或格子键。
- `name`：栏目名。
- `rect`：页面比例坐标 `{x,y,w,h}`。
- `behavior`：填写行为。
- `kind`：`layout` 或 `grid`。

模板没有该表号的 PDF 返回 404。

### `POST /wbs/draft`

1. 读取施工图 PDF 的文字层（封面、总目录、分册目录）。
2. 识别桥梁、道路、隧道和桩号信息。
3. 结合可选 `basis`（工可依据）补全没有施工图的路段。
4. 按模板库 `refs/wbs_rules.json` 生成单位/分部/分项/子分项初稿。

- 不写文件，不执行人工确认、审批或落库。
- 当前不生成隧道划分；桥梁不按墩台/跨数配置合并分部，左右幅体现在分项名称，
  `count.subs` 保持 0。
- 返回 `units`、`count`、`drawings`；每个节点可带识别依据 `src`。

## 配置与公式

`cfg` 保留配置平台的 `fields`、`anchors`、`edges`、`formulas` 元数据；处理链只校验实际
消费的字段，其余元数据原样保留。非法结构返回 422。

- `PDF_REGION.rect` 和 `rects` 是 `{x,y,w,h}` 页面比例坐标。
- 简表 `cells[].rect` 是 `[x,y,w,h]` 外框比例数组，两者不可混用。
- `EXCEL_RANGE.range` 是单个单元格地址，如 `A3`；合并单元格归到左上角。
- 引用优先级：`TEMPLATE` > `COPY` > 同名字段，再补版面/网格。
- 公式支持 `AVG/SUM/MIN/MAX/COUNT/ROUND/IF/PASS_RATE/PASS_RATE_LE`、`@{field}`、
  `&& || !`，保留 JS 风格 `.5` 舍入。
- 字段 ID、格子键和坐标语义沿用 docsvc；保留隐藏文字层过滤、OCR 锁和模板引用优先级。

## 错误

| HTTP 状态 | 场景 |
| --- | --- |
| 400 | 路径越界、文件不存在/不是文件、图片或文档处理失败、公式循环引用、简表版面缺失 |
| 404 | 表样接口找不到该表号的 PDF |
| 422 | 请求字段或配置结构校验失败；`path` 与 `img` 都为空 |
| 503 | 模板资源、OCR 模型或推理依赖不可用 |

错误响应统一为 `{"detail":"..."}`；请求校验失败时为错误数组。错误信息不泄露文件系统
绝对路径、原始图片内容或模型内部细节。

## 重试与幂等

- `GET /diagnostics`、`/ocr/recognize`、`/ocr/daily-logs`、`/ocr/sheet`、
  `/ocr/blank`、`/wbs/draft` 为只读操作，可重试。
- `/ocr/jianbiao`、`/ocr/fill` 在 `out` 非空时写文件；相同 `out` 重试会覆盖输出。
  调用方应确认是否允许覆盖，当前没有幂等键或版本号。
- OCR 结果可能因模型、照片质量和模板更新而变化；不要把 200 当作识别准确的保证。
