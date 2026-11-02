"""启动、关闭和失败路径中的资源归属保持明确。"""

import asyncio

import httpx
import pytest

from app.config import Settings
from app.llm import ModelService
from app.main import create_app


class FailingCloseTransport(httpx.AsyncBaseTransport):
    def __init__(self, error: BaseException):
        self.error = error

    async def aclose(self) -> None:
        raise self.error


class FailingSyncCloseTransport(httpx.BaseTransport):
    def close(self) -> None:
        raise RuntimeError("private sync cleanup details")


def model_service(**kwargs) -> ModelService:
    return ModelService(Settings(_env_file=None), **kwargs)


@pytest.mark.asyncio
async def test_service_closes_both_owned_clients():
    service = model_service()
    await service.close()
    assert service.http_client.is_closed
    assert service.http_async_client.is_closed


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [RuntimeError("close failed"), asyncio.CancelledError()])
async def test_sync_client_is_closed_even_if_async_close_fails(error):
    service = model_service(
        http_async_client=httpx.AsyncClient(transport=FailingCloseTransport(error))
    )
    with pytest.raises(type(error)) as caught:
        await service.close()
    assert caught.value is error
    assert service.http_client.is_closed


def test_async_client_creation_failure_releases_acquired_sync_client(monkeypatch):
    client = httpx.Client()
    error = RuntimeError("async client creation failed")

    def fail_async_client(**kwargs):
        raise error

    monkeypatch.setattr(httpx, "AsyncClient", fail_async_client)
    try:
        with pytest.raises(RuntimeError) as caught:
            model_service(http_client=client)
        assert caught.value is error
        assert client.is_closed
    finally:
        client.close()


@pytest.mark.asyncio
async def test_agent_initialization_failure_closes_service(monkeypatch):
    service = model_service()
    app = create_app(service)

    def fail_model(**kwargs):
        raise RuntimeError("model initialization failed")

    # 在外部集成边界替换模型构造。
    monkeypatch.setattr(service, "chat_model", fail_model)
    with pytest.raises(RuntimeError, match="model initialization failed"):
        async with app.router.lifespan_context(app):
            pytest.fail("startup must fail before serving requests")
    assert service.http_client.is_closed
    assert service.http_async_client.is_closed


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [RuntimeError("close failed"), asyncio.CancelledError()])
async def test_sync_cleanup_failure_preserves_async_error(error, caplog):
    service = model_service(
        http_client=httpx.Client(transport=FailingSyncCloseTransport()),
        http_async_client=httpx.AsyncClient(transport=FailingCloseTransport(error)),
    )
    with pytest.raises(type(error)) as caught:
        await service.close()
    assert caught.value is error
    assert service.http_client.is_closed
    assert "cleanup failed" in caplog.text
    assert "private sync cleanup details" not in caplog.text


def test_sync_cleanup_failure_preserves_construction_error(monkeypatch, caplog):
    error = RuntimeError("async client creation failed")

    def fail_async_client(**kwargs):
        raise error

    monkeypatch.setattr(httpx, "AsyncClient", fail_async_client)
    with pytest.raises(RuntimeError) as caught:
        model_service(http_client=httpx.Client(transport=FailingSyncCloseTransport()))
    assert caught.value is error
    assert "cleanup failed" in caplog.text
    assert "private sync cleanup details" not in caplog.text


@pytest.mark.asyncio
async def test_sync_close_failure_without_prior_error_still_propagates():
    service = model_service(http_client=httpx.Client(transport=FailingSyncCloseTransport()))
    with pytest.raises(RuntimeError, match="private sync cleanup details"):
        await service.close()
    assert service.http_async_client.is_closed
