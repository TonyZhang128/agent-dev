# 监理日记三入口处理语义

状态：`confirmed`。用户于 2026-11-12 明确批准本方案并指定三个路径；正式机器契约见 [journal.openapi.json](../openapi/journal.openapi.json)。

## 1、需求与方案

用户提出三个入口：组合处理、纯 OCR、纯工作内容拆分；明确要求纯 OCR 返回识别框、坐标、置信度和拆分前内容。

| 入口 | 输入 | 输出与行为 |
| --- | --- | --- |
| `POST /ocr/journal` | 图片请求 | 内部顺序执行识别与生成两阶段，输出规定的完整业务 JSON |
| `POST /ocr/journal/recognize` | 沿用现有图片请求的 `path`、`img`、`taskId` 及优先级、数据池限制 | 返回全部检测框、栏目识别结果、置信度和几何位置；不调用语言模型 |
| `POST /ocr/journal/process` | recognize 响应的 data | 映射普通栏目、JournalAgent 生成工作内容，输出与组合入口相同的业务 JSON |

考虑过仅保留组合入口、三个入口共存、强制调用方分步调用三种方案。建议三个入口共存：业务保持一次请求，测试和人工校对后的文本重处理可以独立调用；代价是维护两个新增接口的契约。

不拆部署服务、不引入数据库、持久会话或任务轮询；内部直接调用公共函数，不在同一应用内通过 HTTP 串联接口。

## 2、纯 OCR 返回结构建议

成功使用 OCR 既有包装：`{"status":200,"message":"识别完成","data":...}`。

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `data.taskId` | string/null | 沿用现有回显规则 |
| `data.documentType` | string | 固定 `supervision_diary` |
| `data.image.width`、`height` | integer | EXIF 校正后、缩小前的图片宽高 |
| `data.image.coordinateSpace` | string | 固定 `exif_corrected_original` |
| `data.tablePolygon` | 四点数组 | 检测到的表格四角 |
| `data.boxes` | array | 本次 OCR 返回的全部检测框，包括标签、未归属框以及随后被字段去重逻辑排除的框 |
| `data.fields` | array | 模板全部 11 个栏目，空栏目也保留 |

`boxes` 中每项包含：

- `id`：仅本响应内唯一的 string，用于栏目引用，不作为跨请求稳定标识。
- `text`：OCR 返回的文字，不以栏目清洗后的值覆盖。
- `confidence`：OCR 引擎识别分数，范围 `[0,1]`，不代表业务正确率。
- `polygon`：文字四边形。

`fields` 中每项包含：

- `key`：沿用内部既有栏目编码 `project`、`number`、`supervision_org`、`recorder`、`weather`、`position`、`date`、`reviewer`、`main_work`、`issues`、`next_day_plan`。
- `label`：模板栏目名称。
- `text`：栏目提取后的拆分前文字；空栏目为 null。保留既有去印刷标签、占位清理、日期归一与阅读顺序处理；不执行工作内容分类或模型改写。
- `confidence`：沿用既有字段计算口径，取去重并排除纯标签后的有效框分数算术平均，保留三位小数；没有有效框时为 `0.0`。它不是新增的字段正确率估计。
- `polygon`：模板栏目值区映射到图片后的四边形，区别于实际检测到的文字框。
- `boxIds`：归属该栏目的检测框 ID；空数组表示无已接受的归属框。原始框仍保留在顶层 `boxes`，因此不是按此数组重新拼接就必然等于 `text`。
- `ambiguous`：是否存在归属歧义或栏目来源覆盖不足，沿用现有判定。
- `visibleFraction`：栏目在来源图片中的有效覆盖比例，范围 `[0,1]`。

`key=main_work` 的 `text` 应与组合接口实际送入拆分步骤的完整文本一致：在完整性检查通过时按已有片段保留换行，否则使用完整栏目原文；不先去掉施工、旁站或巡视标题。将整个 `data` 提交给 process，工作原文取本栏目的 `text`。

示意（仅展示一个栏目及一个文字框，非完整成功响应）：

```json
{
  "boxes": [
    {
      "id": "box-1",
      "text": "施工情况：K1+100填筑。",
      "confidence": 0.96,
      "polygon": [[120, 400], [700, 410], [699, 450], [119, 440]]
    }
  ],
  "fields": [
    {
      "key": "main_work",
      "label": "当日主要监理工作情况",
      "text": "施工情况：K1+100填筑。",
      "confidence": 0.96,
      "polygon": [[100, 380], [900, 390], [890, 1000], [90, 990]],
      "boxIds": ["box-1"],
      "ambiguous": false,
      "visibleFraction": 1.0
    }
  ]
}
```

## 3、坐标约定

- 所有对外几何坐标使用同一个坐标系：EXIF 方向校正后、缩小前的图片像素坐标；左上为原点，x 向右，y 向下，允许浮点数。
- 四点按校正画布上的左上、右上、右下、左下顺序映射回图片，保持环绕顺序；图片倾斜时不按映射后的最小 x/y 重新排序。
- 现有 OCR 框位于透视校正画布，输出前通过逆单应变换并还原缩放比例；不能直接把画布坐标当作原图坐标返回。
- 模板值区可能延伸到图片之外，坐标不强行裁剪，以免把来源缺失伪装成完整栏目；由 `visibleFraction` 表达覆盖情况。
- 调用方显示的图片必须采用 EXIF 校正后的方向；叠加到缩略图时按显示宽高等比换算。

## 4、生成入口与内部边界

process 直接接收 recognize 响应的 data，fields 中 11 个栏目必须完整且唯一。校对后的栏目 text 为准，不从 boxes 重新拼接覆盖。通过结构校验后映射普通栏目，仅将 main_work.text 送入 JournalAgent，最终返回 code/message/data/jsonData。详细生成边界、空值和兼容性见 [工作内容生成语义](main-work-processing.md)。

组合入口内部先识别并构建同一个 JournalRecognitionData，再调用同一生成函数；不调用 HTTP、不直接调用另一个 Router 函数。所有非空白记录由 Agent 处理，不保留规则提取路径。OCR 只执行一次，生成失败不返回成功结果。

纯 OCR 的图片校验、坐标、全部框和 11 个栏目保持既有语义，不依赖语言模型。路径、图片和定位失败 400，OCR 资源不可用 503；生成失败 502，请求校验失败 422，错误统一 detail 并脱敏。

## 5、验收标准

1. recognize 不调用语言模型，单张图片只执行一次 OCR，完整保留框、栏目和坐标语义。
2. journal 与 recognize→process 具有同样字段映射、事实约束和最终格式；模型措辞不保证逐字确定性。
3. 人工校对 text 后生成采用校对内容；普通栏目和工作原文不被模型改写。
4. 带完整标题的记录也必须调用 Agent；纯标题由 Agent 判为空，缺少依据的子项不能填套话。
5. 缺失/重复栏目拒绝处理；超限、超时、取消、上游失败与并发隔离均有回归用例。
6. 使用倾斜、EXIF 旋转、超大图片验证坐标回投；使用独立标注的业务文本验证事实与数据，结构合法或 HTTP 200 不能代替内容验收。

旧 `/ocr/daily-logs-new` 路由不恢复。2026-11-12 的两阶段生成批准替代此前规则优先、仅返回三字段的处理方案；其他接口的待确认状态不变。
