"""基于完整mainWork生成施工、旁站、巡视内容，保留来源事实和关键数据。"""

import asyncio
import json

from app.agents.base import StructuredAgent
from app.llm import ModelService
from app.schemas.ocr import MainWorkRequest, MainWorkValues


class MainWorkAgent(StructuredAgent[MainWorkRequest, MainWorkValues]):
    """规则不足时生成三个字段；复用共享runtime、总超时和并发约束。"""

    name = "main_work"
    result_type = MainWorkValues
    temperature = 0.0
    allow_model_fallback = True

    def __init__(self, models: ModelService, *, prompt_name: str | None = None) -> None:
        super().__init__(models, prompt_name=prompt_name or "main_work")
        self._semaphore = asyncio.Semaphore(models.settings.main_work_split_concurrency)

    def user_content(self, request: MainWorkRequest) -> str:
        return json.dumps({"main_work": request.main_work}, ensure_ascii=False)

    async def generate(self, request: MainWorkRequest) -> MainWorkValues:
        async with asyncio.timeout(self.models.settings.main_work_split_timeout_seconds):
            async with self._semaphore:
                return await self.run(request)
