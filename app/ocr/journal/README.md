# 监理日志识别（`app/ocr/journal/`）

新版监理日志照片识别链：以检测到的**表格外框**为唯一锚点，一次透视校正后做**单次整页 OCR**，再按模板把文字框归属到栏目。与旧的逐格识别链 `app/ocr/daily_logs.py` 相互独立，不共享实现。

## 识别流程

```
照片读入 photo.load_photo
        ↓  EXIF 方向校正、透明底铺白、超边等比缩小（≤6000px）
表格检测 table_detection.detect_table
        ↓  LSD 线段 → 共线合并 → 模板拓扑逐线核验 → 四角
画布对齐 alignment.align_canvas
        ↓  一次 warpPerspective 到归一化画布（表格宽 1000~1800px）
单次整页 OCR ocr_adapter.detect_text_boxes
        ↓  RapidOCR，只在这一层适配模型输出
字段归属 field_matching.extract_fields
        ↓  中心点 + 覆盖率打分、歧义拒绝、阅读序、标签剥离、日期归一
JournalRecognition（models.py）
```

关键设计：**OCR 只跑一次**。空字段和歧义字段不会触发重复识别；所有字段都从同一批文字框中分配。

## 模块分工

| 文件 | 职责 |
| --- | --- |
| `pipeline.py` | 同步编排入口 `recognize_journal()`，不含算法 |
| `photo.py` | 解码（Pillow，因 OpenCV 不应用 EXIF 方向）、白底化、尺寸上限 |
| `table_detection.py` | 表格四角检测：共线线段合并、候选四角、模板逐线核验、歧义拒绝 |
| `alignment.py` | 由模板和四角建画布，输出透视矩阵与来源覆盖掩码 |
| `ocr_adapter.py` | RapidOCR → `OcrTextBox` 的唯一适配层，无业务规则 |
| `field_matching.py` | 整页文字框 → 栏目值：归属打分、去重、排序、清洗 |
| `models.py` | 纯数据结构，阶段间输入输出，不放算法 |
| `template.py` | 归一化模板模型、校验与 `load_template()`（缓存） |
| `template_builder.py` | 离线工具：从标准 PDF 构建 `templates/journal.json` |
| `main_work_split.py` | mainWork 拆分：关键词规则优先，Agent 兜底，数据校验守门 |
| `output.py` | 识别结果 → 既有 HTTP 业务结构（camelCase），不补写占位符 |

## 坐标系（三层）

1. **照片像素坐标**：OCR 文字框、检测四角的原始层；
2. **表格归一化坐标**：模板存储层。`rect_in_table = (u, v, w, h)`，原点为**表格左上角**，宽高按表格比例，表外字段允许负值或 >1；
3. **画布像素坐标**：匹配工作层。画布 = 表格 ∪ 表外字段 ∪ 3% 边距，故表格在画布上的位置不是 (0,0)，由 `table_rect_on_canvas` 换算。

`field_matching.bounds_on_canvas` 只做一次线性映射：`画布像素 = 表格在画布上的原点 + 归一化坐标 × 表格在画布上的宽高`。透视畸变仅在 `align_canvas` 处理一次，之后全是轴对齐矩形运算。不用 IoU——文本行框与整格框的 IoU 天然很低，用中心点 + 覆盖率。

## 模板

- 唯一产物：`templates/journal.json`（`schema_version=2`），由 `template_builder.build_template(标准PDF)` 生成，含 `source_sha256` 溯源；
- 运行时只消费表格相对字段、分隔线拓扑和纵横比，不读来源页面尺寸重新标定；
- 必须恰好包含 11 个字段（`FIELD_KEYS`），表内值区必须落在表格范围内；
- 表格核验同时检查**正向证据**（模板线位置有像素支持）与**负向证据**（值格内部不应出现的额外边界），缺失或歧义候选一律抛 `JournalFrameNotFound`，不提供纸张/整图回退。

## mainWork 拆分（独立于几何链）

`split_main_work()` 先按"主要施工情况/旁站情况/巡视情况"三个标题关键词切块；标题不全或前文有业务内容时，原文 ≤4000 字则交 Agent 生成。两条路径都过 `validate_generated_values` 机械校验：数字、正负号、比较符号、桩号、时间/百分比区间、计量值、否定词计数必须与原文一致，且不得新增"完成/合格"等结论。任何事实改动抛 `MainWorkSplitError`，不允许复制整段或补写事实来制造成功。

## 错误与边界

- 图片不可解码 / base64 无效 / path 与 img 都缺 → `ValueError`；
- 表格结构缺失、候选歧义 → `JournalFrameNotFound`（HTTP 映射见 `app/api/ocr.py`）；
- 字段可见比例 < 0.98（没拍到）→ 该字段清空并标记 `ambiguous`，不当作空栏；
- 归属打分前两名覆盖率接近 → 两个字段都标 `ambiguous`，不强行归属。

## 约束

- 不调用语言模型做几何和字段归属（仅 mainWork 兜底一步）；
- 不反向导入 `scripts/` 或 FastAPI；HTTP 入口在 `app/api/ocr.py`；
- 结果对象（`JournalRecognition`）由请求独占，不跨请求共享图像或掩码。
