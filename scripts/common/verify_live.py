"""Real model smoke test: never substitutes a fake inference response."""

import asyncio
import json
import socket
import threading
import time

import httpx
import uvicorn
from fastapi.testclient import TestClient

from app.agents.business_plan import BusinessPlanAgent
from app.config import ROOT, Settings
from app.llm import ModelService
from app.main import create_app
from app.schemas import BusinessPlan, PlanRequest

INSTRUCTION = "员工提交报销申请后，先检查发票是否齐全，齐全则提交部门经理审批，否则通知员工补齐。"


async def direct():
    service = ModelService(Settings())
    try:
        if not await service.ready():
            raise RuntimeError("配置的模型未在服务端列出")
        return await BusinessPlanAgent(service).run(PlanRequest(instruction=INSTRUCTION))
    finally:
        await service.close()


def main(*, gpu_check=None):
    settings = Settings()
    report = {"model": settings.llm_model, "real_inference": False, "http_api": False}
    destination = ROOT / "verification"
    destination.mkdir(exist_ok=True)
    started = time.monotonic()
    try:
        direct_started = time.monotonic()
        plan = asyncio.run(direct())
        report["direct_seconds"] = round(time.monotonic() - direct_started, 2)
        report["direct_model_plan"] = plan.model_dump()
        report["real_inference"] = True
        # Real SDK and real model behind an in-process ASGI client.
        with TestClient(create_app()) as client:
            assert client.get("/health").status_code == 200
            assert client.get("/ready").status_code == 200
            asgi_started = time.monotonic()
            response = client.post("/api/business/plan", json={"instruction": INSTRUCTION})
            report["asgi_seconds"] = round(time.monotonic() - asgi_started, 2)
            if response.status_code != 200:
                raise RuntimeError(f"FastAPI returned {response.status_code}: {response.text}")
            report["api_plan"] = BusinessPlan.model_validate(response.json()).model_dump()
            report["asgi_api"] = True
        # Independently verify actual TCP HTTP, not just an ASGI test transport.
        import os

        api_url = os.environ.get("BUSINESS_API_URL")
        http_started = time.monotonic()
        if api_url:
            with httpx.Client(
                base_url=api_url, timeout=settings.llm_timeout_seconds, trust_env=False
            ) as client:
                response = client.post("/api/business/plan", json={"instruction": INSTRUCTION})
                response.raise_for_status()
                BusinessPlan.model_validate(response.json())
                report["http_api"] = True
        else:
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                sock.listen(16)
                port = sock.getsockname()[1]
                server = uvicorn.Server(uvicorn.Config(create_app(), log_level="warning"))
                thread = threading.Thread(
                    target=server.run, kwargs={"sockets": [sock]}, daemon=True
                )
                thread.start()
                try:
                    deadline = time.monotonic() + 10
                    while not server.started:
                        if not thread.is_alive() or time.monotonic() > deadline:
                            raise RuntimeError("测试 HTTP 服务启动失败")
                        time.sleep(0.05)
                    with httpx.Client(
                        base_url=f"http://127.0.0.1:{port}",
                        timeout=settings.llm_timeout_seconds,
                        trust_env=False,
                    ) as client:
                        response = client.post(
                            "/api/business/plan", json={"instruction": INSTRUCTION}
                        )
                        response.raise_for_status()
                        BusinessPlan.model_validate(response.json())
                        report["http_api"] = True
                finally:
                    server.should_exit = True
                    thread.join(timeout=10)
        report["http_seconds"] = round(time.monotonic() - http_started, 2)
        if gpu_check is not None:
            report.update(gpu_check(settings))
        report["passed"] = True
    except Exception as exc:
        report["passed"] = False
        report["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        report["elapsed_seconds"] = round(time.monotonic() - started, 2)
        (destination / "live-result.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
