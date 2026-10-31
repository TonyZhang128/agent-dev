"""合并后的路由与原智能体必须共同可用。"""

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_ocr_routes_exist_without_changing_agent_liveness(tmp_path):
    settings = Settings(_env_file=None, templates_root=tmp_path / "missing")
    with TestClient(create_app(settings=settings)) as client:
        assert client.get("/health").json() == {"status": "ok"}
        response = client.post("/ocr/fill", json={"form": "missing", "cfg": {}, "values": {}})
        assert response.status_code == 503
        assert set(response.json()) == {"detail"}
        assert client.post("/agents/chat", json={}).status_code == 422
        assert client.post("/wbs/draft", json={}).status_code == 422
