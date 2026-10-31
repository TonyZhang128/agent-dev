# 文档加工与 OCR

原 `docsvc` 已合并进当前智能体项目。唯一应用入口为 `app.main:app`，Python 固定 3.12，默认端口 8309；原 `/agents/*`、`/health`、`/ready` 保持原契约。识别、填表和 WBS 返回草稿，不执行确认、审批或数据库操作。

## 安装与启动

在仓库根目录执行：

```zsh
export UV_CACHE_DIR="$PWD/.cache/uv"
uv sync --locked --group dev
uv run --locked uvicorn app.main:app --host 127.0.0.1 --port 8309
```

继续使用原有 Mac/Linux 服务脚本和 VS Code `Debug API (launch)` 即可。无需启动第二套 docsvc，也不安装其旧 `requirements.txt`。运行依赖统一由 `pyproject.toml` 的 `dependencies` 和 `uv.lock` 管理：PyMuPDF、openpyxl、OpenCV、NumPy、RapidOCR、CPU ONNX Runtime、Pillow。Pillow 被造样图脚本直接使用，因此显式声明。保留现有 FastAPI/Uvicorn/Pydantic/LangChain 版本。

未引入原 requirements 中没有调用代码的 `python-multipart`、预留统计学习依赖 `scikit-learn`，以及仅用于另建训练环境的 `ultralytics`/PyTorch。演示上传脚本使用标准库构造 multipart，服务端接口仍接收 JSON 路径。文字识别使用 RapidOCR 3.x，按识别质量优先选用 PP-OCRv6 Medium（检测与识别）+ PP-OCRv5 Server（方向分类）；这些模型不在安装包内，首次真实识别时从 ModelScope 下载到 `OCR_MODEL_ROOT`，因此该目录必须可写，离线部署需在构建或部署阶段预先放入模型文件。无需下载 LLM 或安装 CUDA。本项目统一使用 `opencv-python`，`uv` 通过 `exclude-dependencies` 忽略 `rapidocr` 声明的 `opencv-python-headless`，避免同时安装两份 `cv2`；也不要同时安装 CPU/GPU 两种 ONNX Runtime 包。Linux 极简系统若导入 OpenCV 提示缺少 `libGL.so.1`，需由部署环境提供对应系统库。

## 路径配置

配置优先级为 API 进程环境、根目录 `.env`、源码默认值；相对路径始终相对于仓库根目录。与 launchd 有关的环境继承规则仍见项目 README。

| 配置 | 默认值 | 内容 |
| --- | --- | --- |
| `TEMPLATES_ROOT` | `data/ocr/templates` | 模板 JSON，只读运行资料 |
| `ADMIN_ROOT` | `data/ocr/admin` | 管理端 `pdf/`、`excel/`、`review/`，查找优先 |
| `ASSET_ROOT` | `data/ocr/assets` | 规范 PDF/Excel；兼容 `library/pdf_dirs.json` 目录改名 |
| `PROJECTS_ROOT` | `data/ocr/projects` | 与 Java 共用的业务数据池，读写边界 |
| `OCR_MODEL_ROOT` | `data/ocr/models` | RapidOCR 模型缓存，必须可写；离线部署预先放入模型 |

当前相邻 daolu_v6 资料可在根目录 `.env` 配置为：

```dotenv
TEMPLATES_ROOT=../daolu_v6_code/6_shujuchi/moban/wenjian/mobanku
ADMIN_ROOT=../daolu_v6_code/4_web_guanli/yuanma/admin
ASSET_ROOT=../6_shujuchi/moban/wenjian/guifanziliao
PROJECTS_ROOT=../6_shujuchi/yewu
```

生产部署改为实际挂载目录。迁移不复制资料库、数据池或原虚拟环境，不修改现有业务文件；`data/ocr/` 和验收输出被 Git 忽略。

最少模板结构：

```text
<TEMPLATES_ROOT>/
  forms/files.json             # {"forms": {表号: {name, pdf:[相对资源路径], excel:{path}}}}
  layouts/jb12.json             # {"forms": {表号: {header:[], key:[]}}}
  layouts/book1.json            # {"forms": {表号: [字段...]}}
  layouts/jianbiao.json         # {"forms": {简表号: {target, name, aspect, cells}}}
  refs/wbs_rules.json           # drawingCues、bridge、road、units
  library/pdf_dirs.json        # 可选，旧目录 → 新目录映射
```

导入和启动不读取这些文件。缺失/无效模板在相关请求返回 `503`，其他智能体继续可用；不指定 `form` 的普通文字识别不要求模板。模板与几何缓存随应用隔离，模板文件更新后重启 API。首次真实 OCR 调用才初始化模型；同一应用的 OCR 推理串行加锁，HTTP 同步路由在线程池中执行。

## HTTP 接口

| 方法和路径 | 请求 | 输出 |
| --- | --- | --- |
| `GET /health/deps` | 无 | 运行库版本、OpenCV 特征与推理设备；`data.ok` 汇总依赖可用性 |
| `POST /ocr/recognize` | `path`，可选 `form=""` | `fields`、`keys`、`lines`、`detail`、`align`、`warning`、`image`、`ms` |
| `POST /ocr/jianbiao` | `path`、`form`、`cfg`；可选 `bound={}`、`out=""` | 简表定位/识别、公式结果、锚点、PDF/Excel 路径 |
| `POST /ocr/fill` | `form`、`cfg`、`values`；可选 `out=""`、`rects={}` | `values`、`errors`、`anchors`、`pdf`、`xlsx`、`xlsxSkipped` |
| `GET /ocr/blank/{form}.png` | 可选 `width=1400`，正整数，上限按 2400 渲染 | 第 1 页 PNG，带缓存头 |
| `GET /ocr/sheet/{form}` | 表号 | `fld_*` 版面栏 + `g*` 可填空格子 |
| `POST /wbs/draft` | `prefix`、`drawings`；可选 `basis` | `units`、`count`、`drawings` 及识别依据 |

除 PNG 外，成功为 `{"status":200,"data":...}`；原 `/health` 继续返回 `{"status":"ok"}`。依赖自检只检查库能否导入，不代表模板齐全或 OCR 准确率达标。

`path`、`out`、`drawings` 为数据池相对路径，兼容 `projects/` 前缀。拒绝绝对路径、目录穿越与越界符号链接；照片必须是文件，施工图支持 PDF 或 `_N.pdf` 单页拆分目录。返回的 `pdf`、`xlsx` 相对 `PROJECTS_ROOT`。`out` 为空不写 PDF、Excel、校正图；非空须以 `.pdf` 结尾，Excel 和校正图分别为同名 `.xlsx`、`.warp.jpg`。文档接口未新增鉴权，应由可信调用方在既有部署边界内使用。

示例：

```zsh
curl --noproxy '*' -fsS http://127.0.0.1:8309/health/deps
curl --noproxy '*' -fsS http://127.0.0.1:8309/ocr/sheet/JB12-4.2.2
curl --noproxy '*' -fsS http://127.0.0.1:8309/ocr/fill \
  -H 'Content-Type: application/json' \
  -d '{"form":"JB12-4.2.2","cfg":{"formulas":[{"target":"rate","expr":"PASS_RATE(94, @{v1}, @{v2})"}]},"values":{"v1":"96.1","v2":"93.2"}}'
```

`cfg` 保留配置平台的 fields/anchors/edges/formulas 元数据；处理所需字段会校验，非法结构返回 `422`。`EXCEL_RANGE.range` 为单个单元格地址（如 `A3`），合并单元格归到左上角。`PDF_REGION.rect` 和 `rects` 是 `{x,y,w,h}` 页面比例坐标；简表 `cells[].rect` 是 `[x,y,w,h]` 外框比例，二者不可混用。

引用优先级为 TEMPLATE > COPY > 同名字段，再补版面/网格；公式支持 `AVG/SUM/MIN/MAX/COUNT/ROUND/IF/PASS_RATE/PASS_RATE_LE`、`@{field}`、`&& || !`，保留 JS 风格 `.5` 舍入。循环引用返回 `400`；单条公式失败进入 `errors` 并留空该计算值，调用方必须检查 `errors`。PDF/Excel 来自相同锚点值；Excel 无对应格子或有冲突时通过 `xlsxSkipped` 返回本次跳过字段。

错误：请求字段/配置校验失败 `422`；路径、图片/文档处理或公式循环错误 `400`；未知表号的表样接口 `404`；模板不可用 `503`。未知表号的照片识别保持原有按栏目文字取值和 warning 行为。对齐 `mismatch` 时不按模板坐标取值；识别结果需要人工核对，不能将 `200` 当作每个字段准确的证明。

沿用原项目的能力边界：表样渲染、格子识别和填表主要处理第 1 页；WBS 尚不生成隧道划分，桥梁不按墩台/跨数配置合并分部，左右幅体现在分项名称，`count.subs` 保持为 0。这次迁移未扩展这些业务规则。

## 辅助脚本

统一使用 `uv run --locked python -m scripts.ocr.<名称>`，不保留第二套 `run.py` 或 requirements 文件。

| 脚本 | 用途 |
| --- | --- |
| `build_files` | 生成表号 → PDF/Excel 表样索引 |
| `build_layouts` | 生成第一册/第二册版面；现行人工坐标需逐表核对后替换 |
| `build_items` | 提取关键项目与结构尺寸 |
| `build_forms`、`build_approval` | 用映射 Excel 和第二册 PDF 生成模板/审批规则 |
| `build_jianbiao` | 补充简表版面，保留人工版面 |
| `build_wbs` | 划分 Excel → JSON 草稿 |
| `check_pdf_excel` | 逐格标记、检查 PDF/Excel 一致性；报告 `verification/ocr/pdf_excel.json` |
| `jl_pdf`、`xlsx_rows`、`common` | PDF/Excel 解析和路径/输出工具 |
| `pdf_dump`、`pdf_items` | PDF 文本导出与文字层 JSON |
| `mock_jianbiao` | 生成简表照片；无 Windows 字体时使用内置中文字体 |
| `demo_jianbiao` | 向 Java 后端上传演示照片，会写业务系统，仅显式需要时运行 |
| `pack_demo_pool` | 读取 Java 已登记文件，打包到 `verification/ocr/pool-demo.tar.gz` |

运行生成脚本前备份模板目录。服务不在请求中修改模板；生成后重启以使缓存失效。

## 测试与验收

```zsh
uv run --locked pytest tests/test_ocr.py tests/test_ocr_integration.py -v
uv run --locked ruff check app tests scripts
uv run --locked ruff format --check app tests scripts
uv run --locked pytest -v
```

离线测试由临时 PDF/Excel/JSON 和图片构成，OCR 只在模型边界模拟；覆盖真实文件生成、合并单元格与印刷文字、公式/引用、WBS、资源隔离和目录限制。原 docsvc 测试依赖 Java 并且兜底 cfg 缺 PDF 锚点，已用确定性夹具替换。

运行中的 API、已有模板和真实简表照片齐备后执行：

```zsh
uv run --locked python -m scripts.common.verify_ocr \
  --photo '<数据池中的简表照片相对路径>' --form JB12-4.2.2
# 可加 --cfg <配置.json> 与 --out <数据池内输出.pdf> 验证文件写入；默认只计算。
uv run --locked python -m scripts.ocr.check_pdf_excel JB12-4.2.2
```

真实验收覆盖存活/依赖、字段/预览、普通 OCR、简表、重算和 WBS，报告写 `verification/ocr/api-live-result.json`。它验证处理链可运行，不评估跨表/手写/低清照片的总体识别准确率。智能体真实验收继续使用 `scripts.common.verify_agents`；离线检查不代表正在运行的服务已更新。Linux GPU、CUDA OCR 和外部 Java 上传演示不属于本机离线验收。

本次迁移范围、实际验证结果与环境限制见 [合并验收记录](docsvc-integration-2026-10-31.md)。
