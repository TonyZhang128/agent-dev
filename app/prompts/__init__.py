"""按包路径加载版本化提示词，不受 Shell 当前工作目录影响。"""

from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=32)
def load_prompt(name: str) -> str:
    """加载提示词；名称可包含子目录，例如 ``intent/business``。

    每一段都必须是 Python 标识符，避免绝对路径或 ``..`` 越过提示词目录。
    """
    parts = name.split("/")
    if not all(part.isidentifier() for part in parts):
        raise ValueError("prompt name must be identifier segments separated by '/'")
    path = Path(__file__).parent.joinpath(*parts[:-1], f"{parts[-1]}.md")
    return path.read_text(encoding="utf-8").strip()
