# 文档加工与 OCR

原 `docsvc` 已合并进当前智能体项目。唯一应用入口为 `app.main:app`，Python 固定 3.12，默认端口 8309；原 `/agents/*`、`/health`、`/ready` 保持原契约。识别、填表和 WBS 返回草稿，不执行确认、审批或数据库操作。

对外接口索引、契约状态和待确认事项见 [interfaces/README.md](../interfaces/README.md)，业务流与路径/输出约束见 [interfaces/guides/ocr.md](../interfaces/guides/ocr.md)，完整 OpenAPI 草案见 [interfaces/drafts/fastapi.openapi.json](../interfaces/drafts/fastapi.openapi.json)。本文保存实现细节、模板目录和验收方法；`/docs` 是运行时实现的投影，不是正式契约。

## 安装与启动

在仓库根目录执行：

```zsh
export UV_CACHE_DIR="$PWD/.cache/uv"
# 默认安装 CPU 版 onnxruntime，供 Mac/无 NVIDIA GPU 的开发环境使用
uv sync --locked --group dev --extra ocr-cpu
# Linux/Windows 且需要 OCR 使用 NVIDIA GPU CUDA EP 时，改用：
# uv sync --locked --group dev --extra ocr-gpu
uv run --locked uvicorn app.main:app --host 127.0.0.1 --port 8309
```

继续使用原有 Mac/Linux 服务脚本和 VS Code `Debug API (launch)` 即可。VS Code 调试直接使用 `.venv`，不执行 `uv` 同步；切换 extra 后需先按上面的命令重新同步环境。无需启动第二套 docsvc，也不安装其旧 `requirements.txt`。运行依赖统一由 `pyproject.toml` 的 `dependencies`、`optional-dependencies` 和 `uv.lock` 管理：PyMuPDF、openpyxl、OpenCV、NumPy、RapidOCR、Pillow，以及通过互斥 extra `ocr-cpu` / `ocr-gpu` 二选一的 `onnxruntime` 或 `onnxruntime-gpu`。Pillow 被造样图脚本直接使用，因此显式声明。保留现有 FastAPI/Uvicorn/Pydantic/LangChain 版本。

未引入原 requirements 中没有调用代码的 `python-multipart`、预留统计学习依赖 `scikit-learn`，以及仅用于另建训练环境的 `ultralytics`/PyTorch。演示上传脚本使用标准库构造 multipart，服务端接口仍接收 JSON 路径。文字识别使用 RapidOCR 3.x，按识别质量优先选用 PP-OCRv6 Medium（检测与识别）+ PP-OCRv5 Server（方向分类）；这些模型不在安装包内。开发环境首次真实识别时从 ModelScope 自动下载到 `OCR_MODEL_ROOT`（该目录必须可写）；离线或容器部署先用 `uv run --locked python -m scripts.models.download_ocr_models --root <目录>` 预置，再通过 `OCR_MODEL_DIR` 只读挂载，避免运行时联网。推理设备由 `OCR_DEVICE` 切换：cuda（需本机 CUDA 12 + cuDNN 9）或 cpu（无 NVIDIA GPU 的环境，如 Mac 开发）；两种模式共用同一套 ONNX 模型，cpu 模式不检查 CUDA。ONNX Runtime 通过两个互斥 extra 选择：`ocr-cpu` 安装 CPU 版 `onnxruntime==1.31.1`，`ocr-gpu` 安装 `onnxruntime-gpu==1.24.4`。两个发行包都提供同名 `onnxruntime` 模块，装在同一环境会互相覆盖文件，因此 `pyproject.toml` 用 `[tool.uv] conflicts` 声明互斥，uv 会拒绝同时启用两个 extra；单独执行不带 extra 的 `uv sync` 不会安装 ONNX Runtime，并会移除已装的那一个。`exclude-dependencies` 仅用于忽略 `rapidocr` 可能声明的 `opencv-python-headless`，避免与项目的 `opencv-python` 同时提供两份 `cv2`。Linux 极简系统若导入 OpenCV 提示缺少 `libGL.so.1`，需由部署环境提供对应系统库。

## 路径配置

配置优先级为 API 进程环境、根目录 `.env`、源码默认值；相对路径始终相对于仓库根目录。与 launchd 有关的环境继承规则仍见项目 README。

| 配置 | 默认值 | 内容 |
| --- | --- | --- |
| `TEMPLATES_ROOT` | `data/ocr/templates` | 模板 JSON，只读运行资料 |
| `ADMIN_ROOT` | `data/ocr/admin` | 管理端 `pdf/`、`excel/`、`review/`，查找优先 |
| `ASSET_ROOT` | `data/ocr/assets` | 规范 PDF/Excel；兼容 `library/pdf_dirs.json` 目录改名 |
| `PROJECTS_ROOT` | `data/ocr/projects` | 与 Java 共用的业务数据池，读写边界 |
| `OCR_MODEL_ROOT` | `.cache/models/ocr` | RapidOCR 模型缓存，开发环境可写自动下载；离线部署用下载脚本预置后只读挂载 |
| `OCR_DEVICE` | `cpu` | 推理设备：`cpu`（默认，适合无 NVIDIA GPU 的开发环境）或 `cuda`（需 CUDA 12 + cuDNN 9 并通过 `--extra ocr-gpu` 安装 onnxruntime-gpu），见下文「推理设备」 |
| `OCR_CUDA_ROOT` | `.cache/cuda` | Windows 项目本地 CUDA 运行库目录（Git 已忽略），仅 cuda 模式使用，见下文「推理设备」 |

### 推理设备

`OCR_DEVICE` 切换 onnxruntime 执行设备，两种模式共用同一套 ONNX 模型：

- `cpu`（默认）：供无 NVIDIA GPU 的环境使用（如 Mac 开发）。通过
  `uv sync --extra ocr-cpu` 安装 CPU 版 `onnxruntime==1.31.1`，不检查 CUDA 运行库，
  直接 CPU 推理。
- `cuda`：通过 `onnxruntime-gpu==1.24.4` 的 CUDA EP 推理。需要安装时带上
  `--extra ocr-gpu`，并确保运行环境有 CUDA 12 + cuDNN 9（1.31 起的 GPU 包改用
  CUDA 13，本项目未采用）；`onnxruntime-gpu` 不附带 CUDA/cuDNN 动态库，
  首次创建引擎时会验证 CUDA 真实可用：不可用直接返回 503，不会静默退回 CPU。
- 两个 extra 互斥，不能同时启用；同时安装会覆盖同名 `onnxruntime` 模块。

`GET /diagnostics` 的「推理设备」除编译进 onnxruntime 的 provider 列表外，还带
`configured`、`device` 和 `runtime` 字段，用于核对 `OCR_DEVICE`、实际设备与已安装发行包是否一致。

- Linux：由系统 CUDA 12 + cuDNN 9 环境提供动态库（`LD_LIBRARY_PATH`）。
- Windows 免安装方案：从 NVIDIA redist 索引下载以下 `windows-x86_64-archive.zip`
  并解压到 `OCR_CUDA_ROOT`（默认 `.cache/cuda`），首次推理前应用会把各包的
  `bin` 目录加入 DLL 搜索路径：

  | 包 | 已验证版本 |
  | --- | --- |
  | `cuda_cudart` | 12.8.90 |
  | `libcublas` | 12.8.5.5 |
  | `libcufft` | 11.4.1.4（提供 `cufft64_11.dll`） |
  | `cudnn`（`_cuda12`） | 9.8.0.87 |

  下载地址形如
  `https://developer.download.nvidia.com/compute/cuda/redist/<包>/windows-x86_64/<包>-windows-x86_64-<版本>-archive.zip`，
  cuDNN 在 `compute/cudnn/redist/cudnn/windows-x86_64/` 下。注意 onnxruntime-gpu
  要求 CUDA 12 系列构建（`>=1.24,<1.25` 已验证；1.31 起改为 CUDA 13，需驱动配套），
  且驱动支持的 CUDA 版本不能低于运行库版本。`GET /diagnostics` 的「推理设备」
  只反映编译进 onnxruntime 的 provider 列表，不代表 CUDA 初始化成功；真实初始化由首次 OCR 调用验证。


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
| `GET /diagnostics` | 无 | 运行库、推理设备、模板/版面/WBS 规则、模型目录与数据池的静态检查；`data.ok` 汇总必需检查，`data.warnings` 记录非致命问题 |
| `POST /ocr/recognize` | `path` 或 `img`（至少提供一个），可选 `form=""` | `fields`、`keys`、`lines`、`detail`、`align`、`warning`、`image`、`ms` |
| `POST /ocr/daily-logs` | `path` 或 `img`（至少提供一个），可选 `taskId=""` | 监理日记（JLB13）固定栏目识别、原始框、`frame`、业务结构 `processed`、`ms` |
| `POST /ocr/daily-logs-new` | 同 `/ocr/daily-logs` | 独立新链路的监理日记识别；单次整页 OCR + 栏目匹配，返回结构相同 |
| `POST /ocr/jianbiao` | `path`、`form`、`cfg`；可选 `bound={}`、`out=""` | 简表定位/识别、公式结果、锚点、PDF/Excel 路径 |
| `POST /ocr/fill` | `form`、`cfg`、`values`；可选 `out=""`、`rects={}` | `values`、`errors`、`anchors`、`pdf`、`xlsx`、`xlsxSkipped` |
| `GET /ocr/blank/{form}.png` | 可选 `width=1400`，正整数，上限按 2400 渲染 | 第 1 页 PNG，带缓存头 |
| `GET /ocr/sheet/{form}` | 表号 | `fld_*` 版面栏 + `g*` 可填空格子 |
| `POST /wbs/draft` | `prefix`、`drawings`；可选 `basis` | `units`、`count`、`drawings` 及识别依据 |

除 PNG 外，成功为 `{"status":200,"data":...}`；原 `/health` 继续返回 `{"status":"ok"}`。`/diagnostics` 只做本地静态检查：不初始化 OCR 引擎、不加载模型、不注册 CUDA DLL、不访问网络、不写文件；`data.ok=false` 时仍返回 HTTP 200。它检查模板清单、版面 JSON、WBS 规则、模型目录和数据池是否可用，但不校验模型文件 sha256，也不代表识别准确率达标；完整模型校验使用 `scripts.models.download_ocr_models --check`。

`/ocr/recognize` 的 `path` 为数据池内照片路径，`img` 为 base64 编码的图片（兼容 `data:image/...;base64,` 前缀）；两者至少提供一个，同时提供时优先使用 `img`，都为空白返回 `422`。`/ocr/daily-logs` 和 `/ocr/daily-logs-new` 使用相同的图片来源规则，但固定识别监理日记的页面栏目，不读取表号、配置、模板或输出文件；可选的 `taskId` 只原样回显，服务不生成任务 ID。`path`、`out`、`drawings` 为数据池相对路径，兼容 `projects/` 前缀。拒绝绝对路径、目录穿越与越界符号链接；照片必须是文件，施工图支持 PDF 或 `_N.pdf` 单页拆分目录。返回的 `pdf`、`xlsx` 相对 `PROJECTS_ROOT`。`out` 为空不写 PDF、Excel、校正图；非空须以 `.pdf` 结尾，Excel 和校正图分别为同名 `.xlsx`、`.warp.jpg`。文档接口未新增鉴权，应由可信调用方在既有部署边界内使用。

示例：

```zsh
curl --noproxy '*' -fsS http://127.0.0.1:8309/diagnostics

# 普通照片识别：path 相对 PROJECTS_ROOT，只读取，不写文件。
curl --noproxy '*' -fsS http://127.0.0.1:8309/ocr/recognize \
  -H 'Content-Type: application/json' \
  -d '{"path":"projects/现场照片.jpg"}'

# 已知表号时传 form：按模板坐标对齐；对齐失败会返回 warning，仅按栏目文字取值。
curl --noproxy '*' -fsS http://127.0.0.1:8309/ocr/recognize \
  -H 'Content-Type: application/json' \
  -d '{"path":"projects/简表照片.jpg","form":"JB12-4.2.2"}'

# 监理日记：固定按表样裁栏，返回原始识别草稿和业务结构；也可用 img 传 base64。
curl --noproxy '*' -fsS http://127.0.0.1:8309/ocr/daily-logs \
  -H 'Content-Type: application/json' \
  -d '{"path":"projects/监理日志照片.jpg","taskId":"123456789012345678"}'

# 新版链路：单次整页 OCR + 固定栏目匹配，返回结构与旧接口相同。
curl --noproxy '*' -fsS http://127.0.0.1:8309/ocr/daily-logs-new \
  -H 'Content-Type: application/json' \
  -d '{"path":"projects/监理日志照片.jpg","taskId":"123456789012345678"}'

curl --noproxy '*' -fsS http://127.0.0.1:8309/ocr/sheet/JB12-4.2.2
curl --noproxy '*' -fsS http://127.0.0.1:8309/ocr/fill \
  -H 'Content-Type: application/json' \
  -d '{"form":"JB12-4.2.2","cfg":{"formulas":[{"target":"rate","expr":"PASS_RATE(94, @{v1}, @{v2})"}]},"values":{"v1":"96.1","v2":"93.2"}}'
```

`/ocr/recognize` 返回 `fields`、`detail`、`lines`、`align`、`warning` 等草稿结果：`fields` 为按栏目提取的字段值，`detail` 说明取值方式（`inline`/`rect`/`right`），`lines` 为原始 OCR 文本框，`align.how` 为 `anchors`/`mismatch`/`none`。识别结果需人工核对，`200` 不代表每个字段都准确。

`/ocr/daily-logs` 复用「找外框 → 透视校正 → 逐格 OCR」，按现场《监理日记》表样返回 `recognized`（`project`、`number`、`supervision_org`、`recorder`、`weather`、`position`、`date`、`reviewer`、`construction`、`witness`、`patrol`、`issues`、`next_day_plan`）和 `detail`；`date` 归一为 `yyyy-mm-dd`，长文本栏保留 OCR 拼接结果。`frame.how` 为 `contour`/`contour+table`/`whole` 等定位方式，`whole` 时 `warning` 提示核对定位。`processed` 是业务结构：`taskId`（请求原样回显，未传为 `null`）、`documentType`（固定 `supervision_diary`）、`common` 和 `fields`；识别不到的栏目为 `null`，不做推断。该接口只读取照片，不写 PDF/Excel，也不生成任务 ID。

`/ocr/daily-logs-new` 是独立实现，返回结构与 `/ocr/daily-logs` 相同：在原图上用横竖线定位表格外框，只做一次透视校正；整页只调用一次 OCR；文字框按栏目区域用中心点和框内覆盖率匹配；印刷栏目名按栏目名近似剥离；歧义或漏框字段最多补充识别 3 次。样例表中 `construction`、`witness`、`patrol` 同属一个 `mainWork` 单元格，当前整格识别后暂时同时回填到这三个字段，后续再按"主要施工情况 / 旁站情况 / 巡视情况"小标题拆分。`frame.how` 为 `contour+table`/`contour`/`whole`，`whole` 时仍返回定位 warning。

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
| `bench_journal` | 批量运行新版监理日志识别，结果写入 `verification/ocr/journal-bench.json` |
| `draw_journal_fields` | 不调用 OCR，把 `FIELD_SPECS` 画到校正页和原照片，输出 `verification/ocr/journal-fields-*.png` |

运行生成脚本前备份模板目录。服务不在请求中修改模板；生成后重启以使缓存失效。

## 测试与验收

```zsh
uv run --locked pytest tests/test_ocr.py tests/test_ocr_recognize.py tests/test_ocr_daily_logs.py tests/test_ocr_journal.py tests/test_ocr_integration.py -v
uv run --locked ruff check app tests scripts
uv run --locked ruff format --check app tests scripts
uv run --locked pytest -v
```

离线测试由临时 PDF/Excel/JSON 和图片构成，OCR 只在模型边界模拟；覆盖真实文件生成、合并单元格与印刷文字、公式/引用、WBS、资源隔离和目录限制。原 docsvc 测试依赖 Java 并且兜底 cfg 缺 PDF 锚点，已用确定性夹具替换。

`tests/test_ocr_recognize.py` 覆盖 `/ocr/recognize` 的响应契约、表号缺省/未知/不匹配、模板坐标对齐和错误映射。其中真实照片用例读取 `data/ocr/imgs/CJ5.jpg`、`data/ocr/imgs/test.jpg` 与 `.cache/models/ocr/` 下的 RapidOCR 模型；照片或模型缺失时自动跳过，干净克隆和 CI 不要求这些本地素材。真实识别结果用于回归印刷体表格字段和页眉文字，手写内容不作准确性断言。`tests/test_ocr_daily_logs.py` 覆盖 `/ocr/daily-logs` 的固定栏目裁剪、日期归一、base64 来源、`taskId` 回显、业务映射、路径/模型错误映射；OCR 同样只在模型边界模拟。`tests/test_ocr_journal.py` 覆盖 `/ocr/daily-logs-new` 的单次整页 OCR、栏目归属、印刷栏目名剥离、补充识别、表格定位、整页兜底和 EXIF 方向。

运行中的 API、已有模板和真实简表照片齐备后执行：

```zsh
uv run --locked python -m scripts.common.verify_ocr \
  --photo '<数据池中的简表照片相对路径>' --form JB12-4.2.2
# 可加 --cfg <配置.json> 与 --out <数据池内输出.pdf> 验证文件写入；默认只计算。
uv run --locked python -m scripts.ocr.check_pdf_excel JB12-4.2.2
```

真实验收覆盖存活/依赖、字段/预览、普通 OCR、简表、重算和 WBS，报告写 `verification/ocr/api-live-result.json`。它验证处理链可运行，不评估跨表/手写/低清照片的总体识别准确率。智能体真实验收继续使用 `scripts.common.verify_agents`；离线检查不代表正在运行的服务已更新。Linux GPU、CUDA OCR 和外部 Java 上传演示不属于本机离线验收。

本次迁移范围、实际验证结果与环境限制见 [合并验收记录](docsvc-integration-2026-10-31.md)。
