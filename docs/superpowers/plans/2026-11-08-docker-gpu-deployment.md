# RTX 5090 Laptop GPU 容器部署修复计划

> 执行方式：按用户已批准的检查建议，在当前开发分支直接修改；保留已有 OCR 注释修改，不提交或发布。

**目标：** 准备可复制到 Linux x86_64 的 Qwen3.5 9B Q4_K_M 与 OCR 权重，补齐业务镜像 CUDA 运行库，提供完整部署与验收步骤。

**设计依据：** 本次对话中的 Docker 检查结果及用户“在本机提前下载……按照你的建议进行修改”的授权。保持既有 HTTP 契约、Python 3.12、锁文件及 Agent/OCR 业务行为。

**方案：** API 的 builder/runtime 共同基于 NVIDIA CUDA 12.9.1 + cuDNN runtime Ubuntu 24.04，显式安装 Python 3.12；不跨发行版复制解释器。vLLM 继续使用带 Qwen35 GGUF 插件的独立镜像。Compose 明确 linux/amd64，适当降低单卡显存占比，并转发既有 mainWork 配置。权重及 checksum 位于 Git 忽略的 .cache/models/。

**备选：** OCR CPU 可以作为故障排查方式，但不作为 GPU 修复的验收结论；把 CUDA 动态库从其他发行版拷进 Python slim 的 ABI/依赖维护成本更高，本次不采用。

**验收与审查重点：**
- 镜像内 Python 3.12、OpenCV、ONNX Runtime 和所需 CUDA/cuDNN 库可加载；真实 CUDA EP 另在目标 GPU 验证。
- 本地业务样本、prod.env、嵌套字节码不进入构建上下文，正式 journal 模板和提示词保留。
- 容器启动入口及 Compose 环境转发行为正确，不变更 API 契约。
- GGUF、config、tokenizer 和三个 ONNX 文件齐全且 SHA256 校验通过；已有正确文件复用，不覆盖模型来源记录。
- ARM Mac 的 amd64 仿真不能替代 NVIDIA GPU 验收；不更新本地业务服务，不停止原有进程。

## 执行步骤

- [x] 复核权重并生成迁移校验清单；缺失/损坏文件才重新下载。
- [x] 启动已有 Colima（不切换默认 context），记录旧镜像缺库失败。
- [x] 修复 Dockerfile、.dockerignore、Compose 和 env 示例；构建后验证运行库与打包边界。
- [x] 用实际 Compose 解析测试既有 mainWork 配置转发，覆盖默认与非默认值；不以源码字符串测试代替行为。
- [x] 更新 docs/docker.md、README 和 scripts/README.md，给出 Laptop GPU 的部署和 OCR 实机验收命令。
- [x] 运行全套检查、独立审查和最终 diff 检查；停止本次启动的验证容器与 Colima。

## 验证记录

- 初始工作区仅 app/ocr/journal/alignment.py 有用户修改，两处注释间距导致已有 Ruff 格式失败。
- 本地 GGUF 目录及三个 OCR 模型已经存在，现有下载脚本的离线检查通过。
- 模型核验：10 个大模型文件和 3 个 ONNX 全部匹配来源 SHA256；连同 MANIFEST 共 14 个条目写入 .cache/models/SHA256SUMS，总体积 5,848,976,409 字节。复用已有完整文件，未重复下载。
- Compose RED/GREEN：新增的实际解析用例先因缺少 MAIN_WORK_SPLIT_* 两个注入项失败 2 项，修复后默认值及覆盖值 2 项均通过。
- 构建排除 RED/GREEN：真实 BuildKit 使用合成夹具，修改前业务照片、prod.env、嵌套 pyc 均未排除；修改后均排除且正式模板/提示词仍在。
- 旧镜像实际构建成功；运行 ctypes.CDLL("libcudart.so.12") 报缺库，复现 GPU OCR 运行库缺失。
- 全套离线检查：410 passed、3 skipped（Windows 专用）、覆盖率 94.02%；Ruff lint、pyright、OpenAPI 与 Shell 语法通过。完整格式检查仍仅有用户已有 alignment.py 两处注释间距失败，未修改。
- 独立审查未发现 Critical/Important；指出文档直接 cp 可能在重复执行时覆盖密钥。按实际影响将其视为部署安全问题，改为文件不存在才创建；纯文档修改按命令语义核对。
- 环境记录：启动前 Colima default 为 Stopped，启动后自动拉起其他项目容器。自动审批最初拒绝停止；用户已明确批准“验证结束后恢复停止”。不单独操作其他容器，结束时恢复整台虚拟机的原状态。

- 新镜像 linux/amd64 实际构建通过，Python 3.12.3；构建时 ctypes 加载六类 CUDA/cuDNN 库成功。随后对真实 libonnxruntime_providers_cuda.so 执行 ldd，无未解析依赖。
- 非 root 容器使用只读 ONNX 挂载启动成功，health/OpenAPI 为 200、无模型时 ready 为 503、非法 Chat 为 422、缺失照片为 400；健康检查 healthy。
- 容器 CPU OCR 仿真未完成：进程 exit 137，guest dmesg 明确记录 global OOM；Colima 共 8 GiB 且同时运行其他项目。保留原配置和其他容器，不扩大资源或弱化测试。
- 原生 Mac CPU 使用同一套模型识别一张合成 TEST 123 图，结果 TEST123，与预期一致。这只能证明模型加载及单个合成样例，不替代 Linux GPU 或真实业务样本验收。
- GPU 实机、GGUF 真实加载及业务质量/并发仍未验证；所需服务器命令已写入 docs/docker.md。
- 验证日志与汇总保存在 verification/docker/（Git 忽略）；任务专用容器和旧基线镜像已清理，保留 highway-agent-api:gpu-check 镜像。
- 清理完成：经用户明确批准，Colima default 已恢复 Stopped；未改默认 Docker context，也未修改已有虚拟机资源配置。未创建提交或推送。
