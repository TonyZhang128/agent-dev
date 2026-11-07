# OCR与本地依赖诊断

当前文档业务仅保留 `POST /ocr/daily-logs-new` 监理日记识别，以及系统级 `GET /diagnostics`。旧照片、简表、填表、表样和WBS入口已删除，不再作为可用能力介绍。

接口流程、请求及失败语义以 [接口指南](../interfaces/guides/ocr.md) 为准；table模板构建、算法、命名和真实验收见 [监理日记模板识别](journal-template-recognition.md)。

## 环境

沿用主项目Python 3.12和uv，不使用独立OCR环境。ONNX Runtime通过互斥extra选择：macOS/CPU使用 `uv sync --locked --group dev --extra ocr-cpu`；Linux NVIDIA使用 `--extra ocr-gpu` 并准备CUDA/cuDNN运行库。不能同时安装两个extra，不带extra的重新sync会移除已安装运行时。

`OCR_MODEL_ROOT` 配置本地模型目录；`OCR_DEVICE` 为cpu或cuda；`OCR_CUDA_ROOT`供CUDA运行库使用。模型、引擎和缓存由当前应用持有，首次请求加载，推理加锁，关闭时释放；不在模块全局初始化昂贵资源。

生产离线部署使用 `uv run --locked python -m scripts.models.download_ocr_models --check` 校验已有权重；需要预下载时见 [Docker部署](docker.md)。本次不引入新模型或依赖。

## 资源与路径

journal的schema2模板随代码发布于 `app/ocr/journal/templates/journal.json`，不是从旧表样库读取。构建源PDF和照片位于忽略提交的 `app/ocr/resources/`；报告在 `verification/ocr/`。模板发布后重启API加载。

HTTP `path` 只能指向 `PROJECTS_ROOT` 数据池内文件，兼容 `projects/` 前缀；拒绝绝对路径、穿越、越界符号链接和目录。也可传base64 `img`，同时传入时img优先。HTTP不写模板、PDF、Excel或固定样例输出。

`TEMPLATES_ROOT`、`ADMIN_ROOT`、`ASSET_ROOT` 仍由现有 `/diagnostics` 静态检查引用，本次没有改变其对外结构；它们不参与journal字段定位。诊断不会初始化引擎、执行推理或访问网络，`ok=false`仍返回200；诊断可用不等于照片识别正确。

## 工具和启动

- `scripts.ocr.build_journal_template`：从PDF生成table相对模板和覆盖图。
- `scripts.ocr.inspect_journal`：真实照片单次OCR、字段覆盖和规则拆分报告，默认不调用LLM。
- `scripts.common.verify_ocr`：调用运行中的API；HTTP检查不能替代逐字段验收。

详细命令见 [模板维护](journal-template-recognition.md)。使用 `zsh scripts/dev/services.sh restart-api` 更新本项目本地API；不停止其他方式启动的服务。服务默认 `127.0.0.1:8309`。
