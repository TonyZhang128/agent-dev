"""下载 RapidOCR 的 ONNX 模型，供离线部署只读挂载。

模型组合与运行时 `app.ocr.form_ocr.rapidocr_params()` 一致：
PP-OCRv6 Medium 做检测与识别，PP-OCRv5 Server 做方向分类。
文件默认写入仓库 `.cache/models/ocr/`（Git 忽略，不进镜像），再由 Compose
只读挂载到容器的 `/app/data/ocr/models`；不联网的部署在构建前先在有网环境执行。

    uv run --locked python -m scripts.models.download_ocr_models
    uv run --locked python -m scripts.models.download_ocr_models --check
    uv run --locked python -m scripts.models.download_ocr_models --root /srv/models/ocr
"""

import argparse
import hashlib
import json
import tempfile
from pathlib import Path

from rapidocr import download_models
from rapidocr.inference_engine.base import FileInfo, InferSession
from rapidocr.utils.typings import EngineType, ModelType, OCRVersion, TaskType

from app.ocr.form_ocr import rapidocr_params

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ROOT = ROOT / ".cache" / "models" / "ocr"
SECTIONS = ("Det", "Cls", "Rec")


def runtime_models() -> dict[str, dict[str, str]]:
    """按运行时参数生成下载/校验共用的模型描述。"""
    params = rapidocr_params(Path("."))
    return {
        section: {
            # 推理引擎与运行时一致：onnxruntime（GPU 版包名为 onnxruntime-gpu，模块名不变）。
            "engine_type": EngineType.ONNXRUNTIME.value,
            "task_type": section.lower(),
            "lang_type": "ch",
            "ocr_version": params[f"{section}.ocr_version"].value,
            "model_type": params[f"{section}.model_type"].value,
        }
        for section in SECTIONS
    }


def download_config(root: Path) -> dict:
    """生成 rapidocr.download_models() 需要的配置，参数与运行时保持一致。"""
    return {
        "Global": {
            "use_det": True,
            "use_cls": True,
            "use_rec": True,
            "model_root_dir": str(root),
        },
        **runtime_models(),
    }


def expected_models() -> dict[str, str]:
    """返回 {模型文件名: sha256}，来源为已安装 rapidocr 包内的模型索引。"""
    files = {}
    for spec in runtime_models().values():
        info = InferSession.get_model_url(
            FileInfo(
                EngineType(spec["engine_type"]),
                OCRVersion(spec["ocr_version"]),
                TaskType(spec["task_type"]),
                spec["lang_type"],
                ModelType(spec["model_type"]),
            )
        )
        files[Path(info["model_dir"]).name] = (info.get("SHA256") or "").lower()
    return files


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_models(root: Path, expected: dict[str, str] | None = None) -> list[str]:
    """离线校验模型是否齐全且 sha256 一致，返回问题列表。"""
    expected = expected_models() if expected is None else expected
    problems = []
    for name, sha in sorted(expected.items()):
        path = root / name
        if not path.is_file():
            problems.append(f"缺少模型文件：{path}")
        elif sha and sha256_file(path) != sha:
            problems.append(f"模型校验失败：{path}")
    return problems


def download(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="rapidocr-config-") as directory:
        # rapidocr.download_models() 读取 YAML/JSON 配置；JSON 是 YAML 子集。
        config_path = Path(directory) / "config.json"
        config_path.write_text(
            json.dumps(download_config(root), ensure_ascii=False), encoding="utf-8"
        )
        download_models(config_path)
    problems = verify_models(root)
    if problems:
        raise SystemExit("\n".join(problems))
    print(f"OCR 模型已就绪：{root}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--root",
        type=Path,
        default=DEFAULT_ROOT,
        help=f"模型输出目录，默认 {DEFAULT_ROOT.relative_to(ROOT)}",
    )
    parser.add_argument("--check", action="store_true", help="只离线校验已有文件，不联网")
    args = parser.parse_args()
    root = args.root.expanduser().resolve()

    if args.check:
        problems = verify_models(root)
        if problems:
            raise SystemExit("\n".join(problems))
        print(f"OCR 模型校验通过：{root}")
        return

    download(root)


if __name__ == "__main__":
    main()
