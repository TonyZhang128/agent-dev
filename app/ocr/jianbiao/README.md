# 简表照片识别（`app/ocr/jianbiao/`）

面向已绑定模板的现场简表照片：先核验表格结构，再做一次透视校正和单次整页 OCR，最后把文字框归属到字段，并输出约定业务 JSON。

本模块只负责“照片识别＋字段归属＋JSON 映射”，不直接写 PDF、Excel，不调用语言模型；HTTP 入口为 `POST /ocr/jianbiao`（`app/api/ocr.py`），结果与诊断文件由 `output.export_recognition_outputs()` 写出。

## 一、当前模板

- 文件：`templates/earthwork.json`，即用户提供的《土方路基抽检记录表》schema2 标注文件。
- 正式模板 ID：`subgrade_spot_check`。
- 兼容别名：`JB12-4.5.2-4`；两种 ID 读取同一模板，输出中的 `documentType` 均为 `subgrade_spot_check`。
- 公共字段：`project`、`number`、`inspector`、`inspect_date`、`position`。
- 记录区：`record_columns × row_groups` 展开为 10 行 × 4 列，共 40 个单元格；加上 5 个公共字段，共 45 个识别值区。
- 模板中的 `table_aspect` 是**表格宽度／高度**；`height_aspect` 向透视校正提供其倒数，不能与旧版高／宽比混用。

字段、标签、行组和单元格均使用相对表格左上角的 `[x, y, width, height]` 归一化坐标。表外字段允许负坐标。

## 二、识别流程

```text
照片路径 / base64 / BGR 内存图像
        ↓
photo.load_photo
        ↓  EXIF 方向校正、透明底铺白、超长边等比缩小
alignment.align_canvas
        ↓  直角候选方向 → LSD 线段 → 候选表格 → 模板逐线核验 → 四点透视校正
ocr_adapter.detect_text_boxes
        ↓  对校正画布执行一次 RapidOCR
field_matching.extract_fields
        ↓  中心点＋覆盖率归属、歧义拒绝、标签剥离、日期归一
pipeline.recognize_jianbiao
        ↓  values＋readings＋alignment
output.build_recognition_response
        ↓  status＋message＋data（common＋10 行 records）
```

表格核验复用 `app/ocr/journal/table_detection.py`。依次尝试原向、90° 逆时针、90° 顺时针和 180°，只有通过同一模板结构核验的方向才能进入 OCR；诊断四角逆变换到原始照片坐标。支持经模板核验的 0°／90°／180°／270° 直角校正，不支持任意旋转角度，也不允许表格检测失败后退回整图 OCR。空字段和歧义字段不会触发逐格重识；模板不匹配的表格在 OCR 前拒绝。

## 三、目录职责

| 文件 | 职责 |
| --- | --- |
| `pipeline.py` | 公开编排入口 `recognize_jianbiao()` |
| `photo.py` | 路径／base64 解码、EXIF 校正、透明底铺白和尺寸限制 |
| `alignment.py` | 直角方向选择、表格结构核验、原图坐标回映射和透视校正 |
| `ocr_adapter.py` | 将共享 RapidOCR 输出转换为 `OcrTextBox` |
| `field_matching.py` | 文字框字段归属、歧义拒绝、标注剥离、文本清洗和日期归一 |
| `template.py` | schema2 模板校验、行组展开、纵横比转换和受控目录加载 |
| `models.py` | 请求独占的识别结果、文字框、字段结果和画布数据结构 |
| `output.py` | 生成约定 JSON；空值输出 `null`，合格率只接受完整数值 |
| `templates/catalog.json` | 正式模板 ID 和兼容别名到模板文件名的受控映射 |
| `templates/earthwork.json` | 土方路基抽检记录表的几何与字段配置 |

## 四、Python 调用

```python
from pathlib import Path

from app.config import Settings
from app.ocr.core.resources import OCRResources, use_resources
from app.ocr.jianbiao import build_recognition_response, recognize_jianbiao

resources = OCRResources(Settings())
try:
    with use_resources(resources):
        result = recognize_jianbiao(
            Path("简表照片.jpg"),
            "subgrade_spot_check",
            task_id="业务任务ID",
        )
    response = build_recognition_response(result)
finally:
    resources.close()
```

公开入口：

```python
recognize_jianbiao(
    photo: np.ndarray | Path | None,
    template_id: str,
    *,
    img: str = "",
    task_id: str = "",
    reader: Reader = detect_text_boxes,
) -> JianbiaoRecognition
```

`img` 非空时优先于 `photo`。`reader` 是 OCR 边界注入点，离线测试可注入文字框读取器；生产默认使用真实 RapidOCR。

`JianbiaoRecognition` 保留：

- `source_template_id`：正式模板 ID；
- `task_id`：调用方任务 ID，未传时输出 `taskId: null`；
- `values`：非空且无歧义的字段值；
- `readings`：全部 45 个字段的值、置信度和歧义标记；
- `alignment`：校正画布、表格四角和逐线支持率。

## 五、JSON 输出

`build_recognition_response(result)` 返回：

```json
{
  "status": 200,
  "message": "识别完成",
  "data": {
    "taskId": "业务任务ID",
    "documentType": "subgrade_spot_check",
    "common": {
      "projectName": null,
      "documentNo": "JB12-4.5.2-4",
      "inspectorName": null,
      "inspectDate": null,
      "position": "实际识别内容"
    },
    "fields": {
      "records": [
        {
          "rowIndex": 1,
          "checkItem": null,
          "standardValue": "实际识别内容",
          "measuredValue": null,
          "passRate": null
        }
      ]
    }
  }
}
```

实际始终输出模板中的全部 10 行；上例为节省篇幅只展示第 1 行。空字段、歧义字段和无法完整解析的合格率输出 `null`，不会用示例值、当前日期或模板占位符补齐。数字与英文单位之间的有意义空格会保留，例如 `0.01 mm`。

## 六、真实图片命令行验收

```bash
uv run --locked python -m scripts.ocr.recognize_jianbiao \
  --photo "verification/ocr/input/土方路基抽检记录表_标注图_框线修正.png" \
  --output "verification/ocr/jianbiao-earthwork" \
  --task-id "20261109-earthwork-001"
```

原始横置手写现场照片可直接传入，无需调用方预先旋转。本机该样本在 GPU 检测阶段内存不足，因此使用 CPU 验收：

```bash
OCR_DEVICE=cpu uv run --locked python -m scripts.ocr.recognize_jianbiao \
  --photo "verification/ocr/input/a7f4c4671870401be760f3f8f68a3fc7.jpg" \
  --output "verification/ocr/jianbiao-earthwork-photo" \
  --task-id "20261109-earthwork-photo-001"
```

输出目录包含：

- `response.json`：与调用方约定结构一致的最终 JSON；
- `diagnostics.json`：45 个字段的识别值、置信度、歧义标记和逐线支持率；
- `aligned.png`：直角旋转和透视校正后的画布。

该命令是本地真实 OCR 入口，不会启动或修改 API。真实识别中的错字会按 OCR 结果保留，应结合 `diagnostics.json` 和原图复核，不能把结构校验通过当作字段内容全部正确。

2026-11-09 已用上述原始横置手写照片完成 CPU 真实 OCR：自动转正、模板核验、透视校正和 10 行 JSON 导出均成功。样本中仍有手写误识别，例如第 1 行项目输出 `△压家度（%）`，第 3 行实测值输出连写的 `444324855`；这些值未用人工推测结果覆盖，交付时必须人工复核。

## 七、测试

```bash
uv run --locked pytest tests/test_ocr_jianbiao.py -q
uv run --locked pytest tests/test_ocr_journal_table_geometry.py tests/test_ocr_journal.py -q
uv run --locked ruff check app/ocr/jianbiao scripts/ocr/recognize_jianbiao.py tests/test_ocr_jianbiao.py
uv run --locked ruff format --check app/ocr/jianbiao scripts/ocr/recognize_jianbiao.py tests/test_ocr_jianbiao.py
uv run --locked pyright
```

覆盖新版模板展开、旧 ID 兼容、用户示例逐值匹配、10 行输出、标注剥离、跨栏歧义拒绝、错误表格在 OCR 前拒绝、横置照片自动转正与原图坐标回映射，以及 base64 与内存图像同链。

带标注的表样图片可验证真实几何链、真实 RapidOCR 和标注清洗，不能证明手写识别准确率。上述手写现场照片只验证单个样本的完整流程，也不代表已达到逐字段准确率要求；手写质量验收仍需更多独立现场样本和人工逐字段标注。
