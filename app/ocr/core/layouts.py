"""模板库版面元数据：表号 → 册 / 表头字段 / 关键项目（只读 layouts/*.json，无 OCR）。

表样坐标是照片识别（form）与填表（jianbiao/fill）共用的模板数据，放 core 供两方取用，
业务模块不互相传递依赖。
"""

from app.ocr.core.resources import get_resources


def layout_of(code: str) -> tuple[str, list[dict], list[dict]]:
    """表号 → (册 jb12 / book1 / any, 字段 [{field, rect, behavior}], 关键项目 [{name, rect}])"""
    if not code:
        return "any", [], []
    layouts = {
        kind: get_resources().load(f"layouts/{kind}.json")["forms"] for kind in ("jb12", "book1")
    }
    if code in layouts["jb12"]:
        v = layouts["jb12"][code]
        return "jb12", v.get("header", []), v.get("key", [])
    if code in layouts["book1"]:
        return "book1", layouts["book1"][code], []
    return "any", [], []
