"""共享 LangChain 模型工厂和 OpenAI 兼容就绪检查。"""

import logging
from typing import Any

import httpx
from langchain_core.language_models import LanguageModelInput
from langchain_openai import ChatOpenAI

from app.config import Settings

logger = logging.getLogger(__name__)


class DeepSeekChatOpenAI(ChatOpenAI):
    """DeepSeek 不支持严格 `json_schema`，改用其 JSON 模式并在本地校验。

    `ProviderStrategy(strict=True)` 会绑定 `json_schema` 响应格式，要求提供方
    严格执行；DeepSeek 对此返回 HTTP 400。这里把请求降级为 `json_object`；
    LangChain 仍会解析 JSON，Pydantic 仍会严格校验结果，并非宽松文本解析。
    """

    def _get_request_payload(
        self,
        input_: LanguageModelInput,
        *,
        stop: list[str] | None = None,
        **kwargs: Any,
    ) -> dict:
        response_format = kwargs.get("response_format")
        if isinstance(response_format, dict) and response_format.get("type") == "json_schema":
            kwargs["response_format"] = {"type": "json_object"}
        return super()._get_request_payload(input_, stop=stop, **kwargs)


class ModelService:
    """持有 HTTP 客户端；所有推理都经过 LangChain Agent。

    注入的客户端由本服务持有，并在应用生命周期结束时关闭。
    云端回退模型共享这些客户端，但使用独立的超时。
    """

    def __init__(
        self,
        settings: Settings,
        *,
        http_client: httpx.Client | None = None,
        http_async_client: httpx.AsyncClient | None = None,
    ):
        self.settings = settings
        self.http_client = http_client or httpx.Client(timeout=settings.llm_timeout_seconds)
        try:
            self.http_async_client = http_async_client or httpx.AsyncClient(
                timeout=settings.llm_timeout_seconds
            )
        except BaseException:
            self._close_sync_after_error()
            raise
        self._models: dict[float, ChatOpenAI] = {}
        self._fallback_models: dict[float, ChatOpenAI] = {}

    @property
    def fallback_enabled(self) -> bool:
        """配置了回退密钥才启用；key 为空时保持原有行为。"""
        return bool(self.settings.llm_fallback_api_key.get_secret_value().strip())

    @property
    def inference_timeout_seconds(self) -> float:
        """Agent 调用总预算：本地尝试加可选的回退尝试。"""
        if not self.fallback_enabled:
            return self.settings.llm_timeout_seconds
        return self.settings.llm_timeout_seconds + self.settings.llm_fallback_timeout_seconds

    def chat_model(self, *, temperature: float = 0) -> ChatOpenAI:
        if temperature not in self._models:
            self._models[temperature] = self._create_model(
                model=self.settings.llm_model,
                base_url=self.settings.llm_base_url,
                api_key=self.settings.llm_api_key.get_secret_value(),
                timeout=self.settings.llm_timeout_seconds,
                temperature=temperature,
                reasoning_effort=self.settings.llm_reasoning_effort,
                model_cls=ChatOpenAI,
                profile={"structured_output": True, "tool_calling": True},
            )
        return self._models[temperature]

    def fallback_chat_model(self, *, temperature: float = 0) -> ChatOpenAI:
        if not self.fallback_enabled:
            raise RuntimeError("fallback model requested without LLM_FALLBACK_API_KEY")
        if temperature not in self._fallback_models:
            self._fallback_models[temperature] = self._create_model(
                model=self.settings.llm_fallback_model,
                base_url=self.settings.llm_fallback_base_url,
                api_key=self.settings.llm_fallback_api_key.get_secret_value(),
                timeout=self.settings.llm_fallback_timeout_seconds,
                temperature=temperature,
                reasoning_effort=self.settings.llm_fallback_reasoning_effort,
                model_cls=DeepSeekChatOpenAI,
                # DeepSeek 没有提供方原生严格 Schema 模式；上面的请求转换会降级为 JSON 模式。
                profile={"structured_output": False, "tool_calling": True},
            )
        return self._fallback_models[temperature]

    def _create_model(
        self,
        *,
        model: str,
        base_url: str,
        api_key: str,
        timeout: float,
        temperature: float,
        reasoning_effort: str,
        model_cls: type[ChatOpenAI],
        profile: dict[str, bool],
    ) -> ChatOpenAI:
        options = {}
        if reasoning_effort:
            options["reasoning_effort"] = reasoning_effort
        return model_cls(
            model=model,
            base_url=base_url,
            api_key=api_key,
            timeout=timeout,
            max_retries=0,
            max_tokens=self.settings.llm_max_tokens,
            temperature=temperature,
            http_client=self.http_client,
            http_async_client=self.http_async_client,
            # 客户端负责传输和代理设置，避免适配器再注入传输层。
            http_socket_options=(),
            use_responses_api=False,
            stream_usage=False,
            profile=profile,
            disabled_params={"parallel_tool_calls": None},
            **options,
        )

    async def ready(self) -> bool:
        response = await self.http_async_client.get(
            self.settings.llm_base_url + "/models",
            headers={"Authorization": "Bearer " + self.settings.llm_api_key.get_secret_value()},
            timeout=5,
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict) or not isinstance(data.get("data"), list):
            raise ValueError("model server returned invalid model metadata")
        return any(
            isinstance(item, dict) and item.get("id") == self.settings.llm_model
            for item in data["data"]
        )

    async def close(self) -> None:
        try:
            await self.http_async_client.aclose()
        except BaseException:
            self._close_sync_after_error()
            raise
        else:
            self.http_client.close()

    def _close_sync_after_error(self) -> None:
        """尝试清理，但不覆盖启动/关闭错误或取消信号。"""
        try:
            self.http_client.close()
        except BaseException as exc:
            # 传输异常文本可能包含提供方或请求细节。
            logger.warning("Synchronous model HTTP client cleanup failed (%s)", type(exc).__name__)
