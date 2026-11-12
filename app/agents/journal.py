"""基于监理日记原文生成简短、结构化的施工、巡视和旁站记录。"""

import asyncio
import json

from app.agents.base import StructuredAgent
from app.llm import ModelService
from app.schemas.ocr import JournalTextRequest, JournalWorkValues


class JournalAgent(StructuredAgent[JournalTextRequest, JournalWorkValues]):
    """基于工作原文生成业务记录；复用共享runtime、总超时和并发约束。"""

    name = "journal"
    result_type = JournalWorkValues
    temperature = 0.0
    allow_model_fallback = True

    def __init__(self, models: ModelService, *, prompt_name: str | None = None) -> None:
        super().__init__(models, prompt_name=prompt_name or "journal")
        self._semaphore = asyncio.Semaphore(models.settings.journal_concurrency)

    def user_content(self, request: JournalTextRequest) -> str:
        return json.dumps({"content": request.content}, ensure_ascii=False)

    async def generate(self, request: JournalTextRequest) -> JournalWorkValues:
        async with asyncio.timeout(self.models.settings.journal_timeout_seconds):
            async with self._semaphore:
                return await self.run(request)
