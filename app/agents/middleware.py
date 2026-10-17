"""Shared LangChain hooks: fail rather than accept partial or refused output."""

from langchain.agents.middleware import AgentMiddleware, AgentState
from langchain_core.messages import AIMessage

from app.errors import InvalidModelOutput


class ResponseGuard(AgentMiddleware):
    def __init__(self, *, allow_tool_calls: bool = False):
        self.allow_tool_calls = allow_tool_calls

    def after_model(self, state: AgentState, runtime):
        message = state["messages"][-1]
        if not isinstance(message, AIMessage):
            raise InvalidModelOutput("model did not return an AI message")
        finish_reason = message.response_metadata.get("finish_reason")
        if finish_reason not in (None, "stop", "tool_calls") or message.additional_kwargs.get(
            "refusal"
        ):
            raise InvalidModelOutput("incomplete or refused output")
        if message.tool_calls:
            if not self.allow_tool_calls:
                raise InvalidModelOutput("unexpected tool call")
        elif not message.text.strip():
            raise InvalidModelOutput("empty output")
        return None

    async def aafter_model(self, state: AgentState, runtime):
        return self.after_model(state, runtime)
