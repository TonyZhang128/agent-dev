import json

from app.agents.base import StructuredAgent
from app.schemas import LogSummary, LogSummaryRequest


class LogSummaryAgent(StructuredAgent[LogSummaryRequest, LogSummary]):
    """将可变结构的工程表单 OCR 或既有文字材料转换为日志片段。

    原样序列化整个对象，保留嵌套字段、空值、实测值及 OCR 原文。
    话术和事实约束集中在 prompts/log_summary.md，不限定某张表的字段结构。
    """

    name = "log_summary"
    result_type = LogSummary

    def user_content(self, request: LogSummaryRequest) -> str:
        return (
            request.content
            if isinstance(request.content, str)
            else json.dumps(request.content, ensure_ascii=False, allow_nan=False)
        )
