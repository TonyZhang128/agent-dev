"""监理日记测试的模型 HTTP/OCR 边界与独立标注记录。"""

import httpx
from fastapi.testclient import TestClient

from app.llm import ModelService
from app.main import create_app
from app.ocr.journal.template import load_template
from tests.ocr_helpers import make_ocr_settings, ocr_result
from tests.test_ocr_journal import field_box, write_photo

MAIN_WORK_PARTS = (
    ("主要施工情况", "K3+280段路基填筑", 0.15, 0.28, 0.95),
    ("旁站情况", "旁站路基碾压", 0.45, 0.58, 0.94),
    ("巡视情况", "巡视挡土墙砌筑", 0.75, 0.88, 0.93),
)
# 无标题的混合业务原文，也必须完整交给模型。
MIXED_MAIN_WORK_PARTS = (
    ("K3+280段路基填筑", "", 0.15, 0.28, 0.95),
    ("旁站路基碾压", "", 0.45, 0.58, 0.94),
    ("巡视挡土墙砌筑", "", 0.75, 0.88, 0.93),
)
FIELD_VALUES = {
    "project": ("成乐高速公路扩容建设", 0.95),
    "number": ("JL-001", 0.96),
    "supervision_org": ("监理机构：测试监理机构", 0.97),
    "recorder": ("记录人：王璐瑶", 0.96),
    "weather": ("晴", 0.98),
    "position": ("专业监理工程师", 0.99),
    "date": ("记录时间：2026年11月11日", 0.99),
    "reviewer": ("审核人：王梦瑶", 0.98),
    "issues": ("挡土墙墙背回填局部压实不足", 0.95),
    "next_day_plan": ("见证水稳基层检测", 0.94),
}


def page_items(shape, parts=MAIN_WORK_PARTS):
    items = []
    for field in load_template().field_layouts():
        if field.key == "main_work":
            for label, text, label_at, value_at, confidence in parts:
                items.append((field_box(shape, field, at=label_at), label, 0.9))
                items.append((field_box(shape, field, at=value_at), text, confidence))
            continue
        text, confidence = FIELD_VALUES[field.key]
        items.append((field_box(shape, field), text, confidence))
    return items


class JournalEngine:
    """整页 OCR 固定返回栏目；mainWork 可按用例替换或省略。"""

    def __init__(self, *, parts=MAIN_WORK_PARTS):
        self.calls = 0
        self.parts = parts

    def __call__(self, picture):
        self.calls += 1
        # 真实生产链应只调用一次OCR；重复调用会返回空，调用次数另作断言。
        if self.calls > 1:
            return ocr_result()
        return ocr_result(*page_items(picture.shape, self.parts))


def completion(content: str, *, finish: str = "stop", model: str = "test-qwen"):
    return httpx.Response(
        200,
        json={
            "id": "test",
            "object": "chat.completion",
            "created": 0,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "finish_reason": finish,
                    "message": {"role": "assistant", "content": content},
                }
            ],
        },
    )


PATROL_KEYS = (
    "inspectionScope",
    "mainConstruction",
    "qualitySafetyEnvironment",
    "problemsAndActions",
)
WITNESS_KEYS = (
    "supervisionProject",
    "constructionProcess",
    "supervisionWork",
    "mainDataRecords",
    "problemsAndResults",
)
GENERATED = {
    "construction": "K3+280段路基填筑",
    "patrol": {**dict.fromkeys(PATROL_KEYS), "mainConstruction": "巡视挡土墙砌筑"},
    "witness": {**dict.fromkeys(WITNESS_KEYS), "supervisionWork": "旁站路基碾压"},
}


def client_for(tmp_path, respond, **overrides):
    settings = make_ocr_settings(tmp_path, **overrides)
    service = ModelService(
        settings,
        http_client=httpx.Client(transport=httpx.MockTransport(respond), trust_env=False),
        http_async_client=httpx.AsyncClient(
            transport=httpx.MockTransport(respond), trust_env=False
        ),
    )
    return settings, TestClient(create_app(service))


def post_journal(client, settings, **kwargs):
    write_photo(settings)
    client.app.state.ocr_resources.engine = kwargs.pop("engine", JournalEngine())
    return client.post("/ocr/journal", json={"path": "journal.png", **kwargs})
