"""拒绝在 Linux 部署中误用 Mac 开发默认值。"""

from app.config import Settings


def main():
    from urllib.parse import urlsplit

    settings = Settings()
    if urlsplit(settings.llm_base_url).port == 11434 or settings.llm_model.startswith("qwen3.5:"):
        raise SystemExit("生产配置仍指向 Ollama 开发环境；请检查 .env 或进程中的 LLM_* 配置。")
    if settings.llm_api_key.get_secret_value() in {"", "CHANGE_ME", "ollama"}:
        raise SystemExit("请配置生产 LLM_API_KEY，并与 vLLM 服务端保持一致。")


if __name__ == "__main__":
    main()
