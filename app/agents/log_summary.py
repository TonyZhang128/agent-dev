import json

from app.agents.base import StructuredAgent
from app.schemas import LogSummary, LogSummaryRequest


class LogSummaryAgent(StructuredAgent[LogSummaryRequest, LogSummary]):
    name = "log_summary"
    result_type = LogSummary

    def user_content(self, request: LogSummaryRequest) -> str:
        return (
            request.content
            if isinstance(request.content, str)
            else json.dumps(request.content, ensure_ascii=False)
        )
