"""按包路径加载版本化提示词，不受 Shell 当前工作目录影响。"""

from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=32)
def load_prompt(name: str) -> str:
    if not name.isidentifier():
        raise ValueError("prompt name must be a Python identifier")
    return Path(__file__).with_name(f"{name}.md").read_text(encoding="utf-8").strip()
