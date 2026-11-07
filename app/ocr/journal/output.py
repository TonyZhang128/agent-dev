"""将已识别字段和 mainWork 分类值映射到既有业务结构。"""

from typing import TypedDict

from app.ocr.journal.models import JournalRecognition
from app.schemas.ocr import MainWorkValues

DOCUMENT_TYPE = "supervision_diary"


class JournalCommon(TypedDict):
    """既有外部协议的公共字段，保持 camelCase 序列化名称。"""

    projectName: str | None
    documentNo: str | None
    supervisionOrg: str | None
    recorderName: str | None
    recorderPosition: str | None
    weather: str | None
    logDate: str | None
    reviewerName: str | None


class MainWorkPayload(TypedDict):
    """mainWork 已分类原文。"""

    construction: str | None
    witness: str | None
    patrol: str | None


class JournalFields(TypedDict):
    """既有协议中的业务栏目。"""

    mainWork: MainWorkPayload
    issues: str | None
    nextDayPlan: str | None


class JournalPayload(TypedDict):
    """HTTP data 内的业务对象；不改变响应模型或 OpenAPI。"""

    taskId: str | None
    documentType: str
    common: JournalCommon
    fields: JournalFields


def build_processed_payload(
    recognition: JournalRecognition, values: MainWorkValues
) -> JournalPayload:
    """只映射已提取值，不补写模板占位符、示例值或当前日期。"""
    recognized = {
        reading.layout.key: reading.value.strip() or None for reading in recognition.readings
    }
    return {
        "taskId": recognition.task_id.strip() or None,
        "documentType": DOCUMENT_TYPE,
        "common": {
            "projectName": recognized.get("project"),
            "documentNo": recognized.get("number"),
            "supervisionOrg": recognized.get("supervision_org"),
            "recorderName": recognized.get("recorder"),
            "recorderPosition": recognized.get("position"),
            "weather": recognized.get("weather"),
            "logDate": recognized.get("date"),
            "reviewerName": recognized.get("reviewer"),
        },
        "fields": {
            "mainWork": {
                "construction": values.construction,
                "witness": values.witness,
                "patrol": values.patrol,
            },
            "issues": recognized.get("issues"),
            "nextDayPlan": recognized.get("next_day_plan"),
        },
    }
