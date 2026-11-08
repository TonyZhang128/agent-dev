# 监理日记：table模板与真实表格对应

运行链为：标准PDF构建table相对模板 → 图片线段与边链 → 候选逐线核验模板行列/合并结构 → 真实table四角对齐 → 单次OCR → 字段归属 → mainWork规则或模型分类。

## 坐标不变量

字段和标签使用 `rect_in_table=(u,v,w,h)`：原点是表格左上角，单位是表格宽高。分隔线同样归一到table。`source_page_size`、`source_table_bounds`只是离线PDF来源信息；运行时字段定位不除以页面尺寸。

`CanvasAlignment.table_rect_on_canvas` 显式记录table在当前画布上的落点。`field_bounds_on_canvas()` 是识别与覆盖图唯一的字段换算入口。增加照片背景、改变table在画布中的位置或大小不改变字段定义。项目名称在table上方，可以 `v<0`；审核人在下方，可以 `v>=1`。

画布由table和表外字段并集加小量边距生成，不按A4纸张外框推定。原图只重采样一次，保留来源覆盖mask。字段名OCR不是定位的必要条件。

## table如何确认

`table_detection.py` 使用OpenCV LSD检测斜向细线，合并共线片段并连接有像素证据的小幅弯曲边链；角点用相邻局部边段求交，不能用最小外接矩形替代真实边。

每个候选将模板的六行、标签列及头部短竖线投影到照片，逐线检查支持；还对每个合并值格检查不应出现的额外竖线。选择依据是模板结构一致性，不奖励面积大，不使用纸张或整图回退。候选不匹配或歧义时抛 `JournalFrameNotFound`，在OCR之前终止。

## 模板构建与部署

```zsh
uv run --locked python -m scripts.ocr.build_journal_template \
  --pdf app/ocr/resources/rj-tamplate.pdf \
  --output app/ocr/journal/templates/journal.json \
  --overlay verification/ocr/journal-template.png
```

当前产物为schema/version 2。构建器读取可见文字层和线/窄矩形边，提取真实单元格及表外值区，再转换到table坐标。缺少标签、结构或出现歧义时失败，不猜坐标。绿色框为值区、红框为标签，发布前逐项核对11个区域。

源PDF/业务照片不提交；部署须带上版本控制内的 `templates/journal.json`。产物记录源SHA。请求只读JSON，不打开PDF；缓存按应用隔离，模板更新后重启API。旧页面比例模板和旧函数别名已删除，不提供兼容分支。

## 本地检查

```zsh
uv run --locked python -m scripts.ocr.inspect_journal \
  --photo app/ocr/resources/jl1.jpg \
  --output verification/ocr/journal --task-id example
```

生成字段覆盖图、来源mask、报告；规则可完整拆分时另写业务JSON，需模型时记录 `requires_model`。工具默认不调用LLM；完整验收调用现有API。无可靠table直接失败，不输出全空“成功”。

业务输出示例 `app/ocr/resources/daily-logs-output.json` 不等于照片逐字真值，不自动覆盖。OCR仍可能误识日期、机构编码、数值和单位；程序不拿示例、当前年份或词库强改原文。

## 接口行为

成功仍为 `{"status":200,"message":"识别完成","data":...}`，请求及业务字段不变。用户已明确批准：无通过结构核验的table或候选歧义时，返回400和 `{"detail":"未检测到监理日志表格，请重新拍摄"}`，不执行OCR或mainWork分类。合法空白表格仍可成功返回空字段。

mainWork先合并文字，再按施工情况、旁站情况、巡视情况关键词提取；规则不足时由Agent基于全文直接生成三个字段。允许整理表达、合并断句和去标题，但保留全部业务事实与关键数据，不摘要、不补充事实。失败仍为既有502。详见 [规则与生成](journal-mainwork-split.md)。

## 保留与删除

保留共享OCR引擎、应用资源隔离、推理锁、关闭路径和当前诊断所需能力，因为仍有真实消费者。删除旧journal别名/结果包装、page/whole回退、旧面积评分、页面比例字段、旧局部阈值修补链、API注释死路由、旧请求类和无消费者的资源寻址；不恢复已移除OCR/WBS接口。

| 模块 | 当前职责 |
| --- | --- |
| `template_builder.py` / `template.py` | 从PDF提取并校验table相对模板 |
| `table_detection.py` | 真实边候选、模板结构核验 |
| `alignment.py` | table落点、包含表外区域的画布及来源mask |
| `photo.py` / `ocr_adapter.py` | 图片解码、EXIF、共享模型四点框适配 |
| `field_matching.py` | table坐标换算、框归属、阅读顺序、原文片段 |
| `main_work_split.py` | 关键词规则、全文生成兜底与关键数据检查 |
| `pipeline.py` / `output.py` | 编排与既有成功结构映射 |

## 验收与回归

TDD锁定行为缺陷，真实图片验收独立执行。`tests/fixtures/journal_table_geometry.json` 只含从真实图片提取的线段、源SHA和人工核对四角，不含照片文字；真实验收仍须从原图重新运行检测和OCR，不能只回放线段或模拟文字框。

分别检查：table四角是否真实、字段框是否正确、文字是否漏/串栏、OCR字符是否正确、mainWork分类是否正确。HTTP200、非空字段数、置信度及覆盖率都不等于业务验收通过。增加空白纸、错误合并格、照片留白变化和table落点变化反例；不能为某张照片写专用坐标或参数。

```zsh
uv run --locked pytest tests/test_ocr_journal*.py tests/test_ocr_main_work_generation.py tests/test_agents_main_work.py tests/test_ocr.py -v
uv run --locked ruff check app tests scripts
uv run --locked ruff format --check app tests scripts
uv run --locked pyright
uv run --locked python -m scripts.docs.check_openapi
uv run --locked pytest -v --cov=app --cov-fail-under=85
```

当前范围为同版式完整表格；裁剪缺边、多页、多表选择和任意版式不在本期。代码检查和单图通过不能外推到未测场景。
