"""业务端层级意图识别；目录来自生成常量，会话上下文由调用方传入。"""

import asyncio
import json

import httpx
from openai import APIConnectionError, APIStatusError, APITimeoutError
from pydantic import ValidationError

from app.agents.base import StructuredAgent
from app.agents.chat import ChatAgent
from app.agents.clarify import ClarificationAgent
from app.agents.intent_catalog import (
    action_belongs_to_page,
    catalog_payload,
    options_for_page,
    page_name,
)
from app.errors import InvalidModelOutput
from app.llm import ModelService
from app.schemas.agents import (
    BusinessIntentClassification,
    BusinessIntentOption,
    BusinessIntentRequest,
    BusinessIntentResult,
    ChatRequest,
    ClarifyRequest,
)
from app.schemas.intent_catalog_generated import CATALOG_VERSION

MIN_CONFIDENCE = 0.65
MAX_CLARIFICATION_ATTEMPTS = 10
CLARIFY_TIMEOUT_SECONDS = 30.0


class BusinessIntentAgent(StructuredAgent[BusinessIntentRequest, BusinessIntentClassification]):
    """一次推理输出 page/action；页面级结果再调用 Chat 澄清模式。"""

    name = "intent_business"
    result_type = BusinessIntentClassification
    # 目录 + 提示词接近上下文上限；Schema 仅通过 response_format 传递。
    include_schema_in_prompt = False

    def __init__(
        self,
        models: ModelService,
        chat_agent: ChatAgent | None = None,
        clarify_agent: ClarificationAgent | None = None,
    ):
        self.chat_agent = chat_agent if chat_agent is not None else ChatAgent(models)
        self.clarify_agent = (
            clarify_agent if clarify_agent is not None else ClarificationAgent(models)
        )
        super().__init__(models, prompt_name="intent/business")

    def user_content(self, request: BusinessIntentRequest) -> str:
        return json.dumps(
            {
                "text": request.message,
                "current_page": request.current_page,
                "last_navigation": (
                    request.last_navigation.model_dump()
                    if request.last_navigation is not None
                    else None
                ),
                "pending_clarification": (
                    request.pending_clarification.model_dump()
                    if request.pending_clarification is not None
                    else None
                ),
                "catalog": catalog_payload(),
            },
            ensure_ascii=False,
        )

    async def run(self, request: BusinessIntentRequest) -> BusinessIntentResult:
        async with asyncio.timeout(self.models.settings.llm_timeout_seconds) as deadline:
            classification = await super().run(request)
            return await self._respond(classification, request, deadline)

    async def _respond(
        self,
        classification: BusinessIntentClassification,
        request: BusinessIntentRequest,
        deadline: asyncio.Timeout,
    ) -> BusinessIntentResult:
        if classification.kind == "chat":
            chat = await self.chat_agent.run(
                ChatRequest(
                    user_id=request.user_id,
                    session_id=request.session_id,
                    message=request.message,
                    history=request.history,
                )
            )
            return BusinessIntentResult(
                status="chat",
                page=None,
                action=None,
                confidence=classification.confidence,
                message=chat.reply,
                options=None,
                catalog_version=CATALOG_VERSION,
            )
        if classification.kind == "unknown":
            return self._unknown(classification.confidence)

        page = classification.page
        if page is None:
            raise InvalidModelOutput("navigate result requires a page")
        action = classification.action
        if action is not None and not action_belongs_to_page(page, action):
            raise InvalidModelOutput("action does not belong to page")
        if (
            action is not None
            and classification.confidence >= MIN_CONFIDENCE
            and not classification.needs_clarification
        ):
            return BusinessIntentResult(
                status="resolved",
                page=page,
                action=action,
                confidence=classification.confidence,
                message=None,
                options=None,
                catalog_version=CATALOG_VERSION,
            )
        return await self._clarify(page, classification.confidence, request, deadline)

    async def _clarify(
        self,
        page: str,
        confidence: float,
        request: BusinessIntentRequest,
        deadline: asyncio.Timeout,
    ) -> BusinessIntentResult:
        options = options_for_page(page)
        attempts = 0
        pending = request.pending_clarification
        if pending is not None and pending.page == page:
            attempts = pending.attempts
        if attempts >= MAX_CLARIFICATION_ATTEMPTS:
            return BusinessIntentResult(
                status="unknown",
                page=None,
                action=None,
                confidence=confidence,
                message="已多次澄清仍未确定具体功能，请重新描述要办理的业务。",
                options=None,
                catalog_version=CATALOG_VERSION,
            )

        clarify_request = ClarifyRequest(
            user_id=request.user_id,
            session_id=request.session_id,
            history=request.history,
            message=request.message,
            page=page,
            options=options,
        )
        try:
            async with asyncio.timeout(
                min(CLARIFY_TIMEOUT_SECONDS, self.models.settings.llm_timeout_seconds)
            ):
                reply = await self.clarify_agent.run(clarify_request)
        except (
            APIConnectionError,
            APIStatusError,
            APITimeoutError,
            httpx.HTTPError,
            InvalidModelOutput,
            ValidationError,
            TimeoutError,
        ):
            # 总预算耗尽仍应按 504 返回；只有澄清子预算不足才降级为确定性文案。
            if deadline.expired():
                raise
            message = self._fallback_message(page, options)
        else:
            message = reply.reply

        return BusinessIntentResult(
            status="clarify",
            page=page,
            action=None,
            confidence=confidence,
            message=message,
            options=options,
            catalog_version=CATALOG_VERSION,
        )

    def _unknown(self, confidence: float) -> BusinessIntentResult:
        return BusinessIntentResult(
            status="unknown",
            page=None,
            action=None,
            confidence=confidence,
            message="我还不能确定你要进入哪个业务页面，请再具体说明要办理的业务。",
            options=None,
            catalog_version=CATALOG_VERSION,
        )

    @staticmethod
    def _fallback_message(page: str, options: list[BusinessIntentOption]) -> str:
        names = "、".join(option.name for option in options)
        return f"你想在「{page_name(page)}」中执行哪个操作？可选：{names}。"
