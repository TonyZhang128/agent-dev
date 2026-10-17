"""Load versioned prompts relative to this package, independent of the shell cwd."""

from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=32)
def load_prompt(name: str) -> str:
    if not name.isidentifier():
        raise ValueError("prompt name must be a Python identifier")
    return Path(__file__).with_name(f"{name}.md").read_text(encoding="utf-8").strip()
