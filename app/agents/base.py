"""可复用的类型化 Agent 流程；HTTP 和模型提供方不进入业务规则。"""

from abc import ABC, abstractmethod
from typing import Any

from langchain_core.messages import AnyMessage, HumanMessage
from pydantic import BaseModel, ValidationError

from app.agents.history import trim_history
from app.agents.runtime import build_agent, invoke_agent, prepared_schema, system_prompt
from app.errors import InvalidModelOutput
from app.llm import ModelService
from app.prompts import load_prompt
from app.schemas import ConversationRequest, RequestContext


class BaseAgent[RequestT: BaseModel, ResultT: BaseModel](ABC):
    name: str
    temperature = 0.0
    dynamic_schema = False

    def __init__(self, models: ModelService):
        self.models = models
        self.prompt = load_prompt(self.name)
        self.agent = None if self.dynamic_schema else self._build()

    def _build(self, schema: dict | None = None):
        return build_agent(
            self.models,
            name=self.name,
            prompt=self.prompt,
            schema=schema,
            temperature=self.temperature,
        )

    def response_schema(self, request: RequestT) -> dict | None:
        return None

    def conversation_messages(self, request: ConversationRequest, current: str) -> list[AnyMessage]:
        schema = prepared_schema(self.response_schema(request), self.name)
        return trim_history(
            request.history,
            current,
            system_prompt=system_prompt(self.prompt, schema),
            schema=schema,
            settings=self.models.settings,
        )

    @abstractmethod
    def messages(self, request: RequestT) -> list[AnyMessage]:
        """用已校验的业务输入构建请求局部消息。"""

    @abstractmethod
    def parse_result(self, state: dict[str, Any]) -> ResultT:
        """把经过检查的 Agent 状态转换为业务响应。"""

    async def run(self, request: RequestT) -> ResultT:
        # 动态 Schema 属于请求局部状态，不得修改共享的已编译 Agent。
        agent = self.agent if self.agent is not None else self._build(self.response_schema(request))
        metadata = (
            {"user_id": request.user_id, "session_id": request.session_id}
            if isinstance(request, RequestContext)
            else None
        )
        state = await invoke_agent(agent, self.models, self.messages(request), metadata=metadata)
        return self.parse_result(state)


class StructuredAgent[RequestT: BaseModel, ResultT: BaseModel](BaseAgent[RequestT, ResultT]):
    result_type: type[ResultT]

    def _build(self, schema: dict | None = None):
        return super()._build(
            schema if schema is not None else self.result_type.model_json_schema()
        )

    def response_schema(self, request: RequestT) -> dict:
        return self.result_type.model_json_schema()

    @abstractmethod
    def user_content(self, request: RequestT) -> str:
        """序列化已校验的业务输入，不改变其中的事实。"""

    def messages(self, request: RequestT) -> list[AnyMessage]:
        if isinstance(request, ConversationRequest):
            return self.conversation_messages(request, self.user_content(request))
        return [HumanMessage(content=self.user_content(request))]

    def parse_result(self, state: dict[str, Any]) -> ResultT:
        try:
            return self.result_type.model_validate(state.get("structured_response"))
        except ValidationError as exc:
            raise InvalidModelOutput("agent response failed business validation") from exc
