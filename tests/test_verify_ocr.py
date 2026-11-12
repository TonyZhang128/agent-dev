"""真实依赖验收脚本必须覆盖两阶段与组合入口的业务字段一致性。"""

import copy
import json

import httpx
import pytest

from scripts.common.verify_ocr import verify
from tests.test_ocr_journal_generation import recognition_input


@pytest.mark.parametrize("corrupt", [False, True])
def test_verify_compares_two_stage_and_combined_business_fields(corrupt):
    recognized = recognition_input(None)
    common = dict.fromkeys(
        (
            "projectName",
            "documentNo",
            "supervisionOrg",
            "recorderName",
            "recorderPosition",
            "weather",
            "logDate",
            "reviewerName",
        )
    )
    fields = {
        "mainWork": {
            "content": "",
            "construction": None,
            "patrol": dict.fromkeys(
                (
                    "inspectionScope",
                    "mainConstruction",
                    "qualitySafetyEnvironment",
                    "problemsAndActions",
                )
            ),
            "witness": dict.fromkeys(
                (
                    "supervisionProject",
                    "constructionProcess",
                    "supervisionWork",
                    "mainDataRecords",
                    "problemsAndResults",
                )
            ),
        },
        "issues": None,
        "nextDayPlan": None,
    }
    business = {
        "code": 200,
        "message": "success",
        "data": {"jsonData": {"common": common, "fields": fields}},
    }
    calls = []

    def respond(request):
        calls.append(request.url.path)
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        if request.url.path == "/diagnostics":
            return httpx.Response(200, json={"data": {"ok": True}})
        if request.url.path == "/ocr/journal/recognize":
            return httpx.Response(
                200, json={"status": 200, "message": "识别完成", "data": recognized}
            )
        if request.url.path == "/ocr/journal/process":
            assert json.loads(request.content) == recognized
            return httpx.Response(200, json=business)
        combined = copy.deepcopy(business)
        if corrupt:
            combined["data"]["jsonData"]["common"]["projectName"] = "不应凭空出现的工程"
        return httpx.Response(200, json=combined)

    with httpx.Client(base_url="http://test", transport=httpx.MockTransport(respond)) as client:
        if corrupt:
            with pytest.raises(ValueError):
                verify(client, "photo.png")
        else:
            report = verify(client, "photo.png")
            assert report["passed"] is True
            assert set(calls) == {
                "/health",
                "/diagnostics",
                "/ocr/journal/recognize",
                "/ocr/journal/process",
                "/ocr/journal",
            }
