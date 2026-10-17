"""Reusable typed structured-agent flow; HTTP and providers stay outside business rules."""

from abc import ABC, abstractmethod

from langchain_core.messages import HumanMessage
from pydantic import BaseModel, ValidationError

from app.agents.runtime import build_agent, invoke_agent
from app.errors import InvalidModelOutput
from app.llm import ModelService
from app.prompts import load_prompt


class StructuredAgent[RequestT: BaseModel, ResultT: BaseModel](ABC):
    name: str
    result_type: type[ResultT]
    dynamic_schema = False

    def __init__(self, models: ModelService):
        self.models = models
        self.prompt = load_prompt(self.name)
        self.agent = (
            None if self.dynamic_schema else self._build(self.result_type.model_json_schema())
        )

    def _build(self, schema: dict):
        return build_agent(self.models, name=self.name, prompt=self.prompt, schema=schema)

    def response_schema(self, request: RequestT) -> dict:
        return self.result_type.model_json_schema()

    @abstractmethod
    def user_content(self, request: RequestT) -> str:
        """Serialize validated business input without changing its facts."""

    async def run(self, request: RequestT) -> ResultT:
        # Custom intent enums are request-local; never mutate a shared compiled agent.
        agent = self.agent if self.agent is not None else self._build(self.response_schema(request))
        state = await invoke_agent(
            agent, self.models, [HumanMessage(content=self.user_content(request))]
        )
        try:
            return self.result_type.model_validate(state.get("structured_response"))
        except ValidationError as exc:
            raise InvalidModelOutput("agent response failed business validation") from exc
