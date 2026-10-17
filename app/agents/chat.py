from langchain_core.messages import AIMessage, HumanMessage

from app.agents.runtime import build_agent, invoke_agent
from app.llm import ModelService
from app.prompts import load_prompt
from app.schemas import ChatRequest, ChatResponse


class ChatAgent:
    def __init__(self, models: ModelService):
        self.models = models
        self.agent = build_agent(models, name="chat", prompt=load_prompt("chat"), temperature=0.7)

    async def run(self, request: ChatRequest) -> ChatResponse:
        messages = [
            (HumanMessage if item.role == "user" else AIMessage)(content=item.content)
            for item in request.history
        ]
        messages.append(HumanMessage(content=request.message))
        state = await invoke_agent(self.agent, self.models, messages)
        return ChatResponse(
            reply=state["messages"][-1].text.strip(), model=self.models.settings.llm_model
        )
