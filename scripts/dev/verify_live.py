"""macOS Ollama 推理、Q4_K_M 和 Metal 显存分配验证。"""

import sys
from urllib.parse import urlsplit

import httpx

from app.config import Settings
from scripts.common.verify_live import main as verify_live


def check_ollama_gpu(settings: Settings) -> dict:
    url = urlsplit(settings.llm_base_url)
    if url.hostname not in {"127.0.0.1", "localhost"} or url.port != 11434:
        raise RuntimeError(
            "Mac GPU 验收要求本机 Ollama :11434；其他服务使用 scripts.common.verify_live"
        )
    report = {}
    with httpx.Client(timeout=10, trust_env=False) as client:
        response = client.post(
            "http://127.0.0.1:11434/api/show", json={"model": settings.llm_model}
        )
        response.raise_for_status()
        details = response.json()["details"]
        report["model_details"] = details
        if details.get("quantization_level") != "Q4_K_M":
            raise RuntimeError("实际量化等级不是预期的 Q4_K_M")
        response = client.get("http://127.0.0.1:11434/api/ps")
        response.raise_for_status()
        loaded = response.json()["models"]
        report["loaded_models"] = loaded
        report["gpu_verified"] = any(
            m.get("name") == settings.llm_model and m.get("size_vram", 0) > 0 for m in loaded
        )
        if not report["gpu_verified"]:
            raise RuntimeError("推理成功，但未能确认模型 GPU 分配；请查看 ollama ps 和服务日志")
    return report


def main():
    if sys.platform != "darwin":
        raise RuntimeError("此验收仅用于 macOS；Linux 使用 bash scripts/prod/verify.sh")
    verify_live(gpu_check=check_ollama_gpu)


if __name__ == "__main__":
    main()
