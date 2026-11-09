"""使用真实 RapidOCR 识别简表照片，导出约定 JSON、校正图和逐字段诊断。"""

import argparse
import json
from pathlib import Path

from app.config import Settings
from app.ocr.core.resources import OCRResources, use_resources
from app.ocr.jianbiao import build_recognition_response, recognize_jianbiao
from app.ocr.jianbiao.output import JianbiaoResponse, export_recognition_outputs


def recognize_photo(
    photo: Path,
    output: Path,
    template_id: str = "subgrade_spot_check",
    task_id: str = "",
) -> JianbiaoResponse:
    """执行一次完整识别；响应文件只包含约定结构，诊断信息另行保存。"""
    resources = OCRResources(Settings())
    try:
        with use_resources(resources):
            recognition = recognize_jianbiao(photo, template_id, task_id=task_id)
    finally:
        resources.close()
    export_recognition_outputs(recognition, output)
    return build_recognition_response(recognition)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--photo", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("verification/ocr/jianbiao"))
    parser.add_argument("--template-id", default="subgrade_spot_check")
    parser.add_argument("--task-id", default="")
    arguments = parser.parse_args(argv)
    response = recognize_photo(
        arguments.photo,
        arguments.output,
        template_id=arguments.template_id,
        task_id=arguments.task_id,
    )
    print(json.dumps(response, ensure_ascii=False, indent=2))
    print(f"已导出识别结果：{arguments.output}")


if __name__ == "__main__":
    main()
