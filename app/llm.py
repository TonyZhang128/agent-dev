"""Shared LangChain model factory and OpenAI-compatible readiness probe."""

import logging

import httpx
from langchain_openai import ChatOpenAI

from app.config import Settings

logger = logging.getLogger(__name__)


class ModelService:
    """Own HTTP clients; all inference runs through LangChain agents.

    Injected clients are owned by this service and closed with the app lifespan.
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

    def chat_model(self, *, temperature: float = 0) -> ChatOpenAI:
        if temperature not in self._models:
            options = {}
            if self.settings.llm_reasoning_effort:
                options["reasoning_effort"] = self.settings.llm_reasoning_effort
            self._models[temperature] = ChatOpenAI(
                model=self.settings.llm_model,
                base_url=self.settings.llm_base_url,
                api_key=self.settings.llm_api_key.get_secret_value(),
                timeout=self.settings.llm_timeout_seconds,
                max_retries=0,
                max_tokens=self.settings.llm_max_tokens,
                temperature=temperature,
                http_client=self.http_client,
                http_async_client=self.http_async_client,
                # Our clients own transport/proxy settings; avoid adapter transport injection.
                http_socket_options=(),
                use_responses_api=False,
                stream_usage=False,
                profile={"structured_output": True, "tool_calling": True},
                disabled_params={"parallel_tool_calls": None},
                **options,
            )
        return self._models[temperature]

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
        """Attempt cleanup without replacing a startup/shutdown error or cancellation."""
        try:
            self.http_client.close()
        except BaseException as exc:
            # Transport exception text can include provider or request details.
            logger.warning("Synchronous model HTTP client cleanup failed (%s)", type(exc).__name__)
