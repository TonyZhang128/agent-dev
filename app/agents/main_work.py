"""监理日志 mainWork 的原文单元分类；只返回 ID → 类别，不生成字段文本。"""

import asyncio
import json

from app.agents.base import StructuredAgent
from app.llm import ModelService
from app.schemas.ocr import MainWorkSplitPlan, MainWorkSplitRequest


class MainWorkSplitAgent(StructuredAgent[MainWorkSplitRequest, MainWorkSplitPlan]):
    """把原文单元分类到 construction/witness/patrol/unknown。

    请求之间只共享编译后的 Agent 和并发信号量；单元、动态结果均由请求局部构造。
    只有标题/强标记规则无法完整拆分时，编排层才会调用该能力；模型失败或结果不合格
    时返回受控错误，不追加修复调用。配置 LLM_FALLBACK_API_KEY 时，主模型连接失败、
    超时或上游错误会按运行时配置回退到云端模型一次。
    """

    name = "main_work_split"
    result_type = MainWorkSplitPlan
    temperature = 0.0
    allow_model_fallback = True

    def __init__(self, models: ModelService, *, prompt_name: str | None = None):
        # Agent 名称用于 JSON Schema 标题；提示词文件名独立，避免改动已有命名。
        super().__init__(models, prompt_name=prompt_name or "main_work")
        # 本地模型默认串行；排队与推理共享同一个总超时预算。
        self._semaphore = asyncio.Semaphore(models.settings.main_work_split_concurrency)

    def user_content(self, request: MainWorkSplitRequest) -> str:
        # start/end 是内部坐标，不进入提示词，也不增加 Token 消耗。
        units = [
            {
                "id": unit.unit_id,
                "text": unit.text,
                "kind": "heading" if unit.is_heading else "body",
                "heading_category": unit.heading_category,
            }
            for unit in request.units
        ]
        return json.dumps({"units": units}, ensure_ascii=False, allow_nan=False)

    async def plan(self, request: MainWorkSplitRequest) -> MainWorkSplitPlan:
        timeout = self.models.settings.main_work_split_timeout_seconds
        async with asyncio.timeout(timeout):
            async with self._semaphore:
                return await self.run(request)
