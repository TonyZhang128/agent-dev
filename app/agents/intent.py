import json

from app.agents.base import StructuredAgent
from app.errors import InvalidModelOutput
from app.schemas import IntentDefinition, IntentRequest, IntentResult

DEFAULT_INTENTS = (
    IntentDefinition(label="query", description="查询已有记录、状态或资料"),
    IntentDefinition(label="create", description="新增订单、申请或业务记录"),
    IntentDefinition(label="update", description="修改已有业务记录或信息"),
    IntentDefinition(label="cancel", description="取消或撤销已有业务申请、订单"),
    IntentDefinition(label="help", description="寻求操作方法、使用指导或问题解答"),
    IntentDefinition(label="chat", description="问候、闲聊或一般交流"),
)


class IntentAgent(StructuredAgent[IntentRequest, IntentResult]):
    name = "intent"
    result_type = IntentResult
    dynamic_schema = True

    def response_schema(self, request: IntentRequest) -> dict:
        intents = request.intents or DEFAULT_INTENTS
        schema = IntentResult.model_json_schema()
        schema["properties"]["intent"]["enum"] = [item.label for item in intents] + ["unknown"]
        return schema

    def user_content(self, request: IntentRequest) -> str:
        intents = request.intents or DEFAULT_INTENTS
        return json.dumps(
            {"text": request.text, "intents": [item.model_dump() for item in intents]},
            ensure_ascii=False,
        )

    async def run(self, request: IntentRequest) -> IntentResult:
        result = await super().run(request)
        labels = [item.label for item in (request.intents or DEFAULT_INTENTS)]
        if result.intent not in labels + ["unknown"]:
            raise InvalidModelOutput("model returned an intent outside the allowed labels")
        if result.intent == "unknown" or result.confidence < 0.65 or result.needs_clarification:
            result.intent = "unknown"
            result.needs_clarification = True
        return result
