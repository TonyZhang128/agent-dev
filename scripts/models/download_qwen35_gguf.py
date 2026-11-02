"""下载 Qwen3.5-9B GGUF 量化权重，并组装成 vLLM 可直接加载的模型目录。

默认从 ModelScope 取 unsloth/Qwen3.5-9B-GGUF 的 Q4_K_M 权重，再从
Qwen/Qwen3.5-9B 补齐 config.json 与 tokenizer——GGUF 单独一个文件不能作为
vLLM 的模型目录。文件落在仓库 .cache/models/ 下，不进 Git、不打进镜像。

    uv run --locked python -m scripts.models.download_qwen35_gguf
    uv run --locked python -m scripts.models.download_qwen35_gguf --quant Q5_K_M
    uv run --locked python -m scripts.models.download_qwen35_gguf --vision
    uv run --locked python -m scripts.models.download_qwen35_gguf --check
    uv run --locked python -m scripts.models.download_qwen35_gguf --list
"""

import argparse
import hashlib
import json
import struct
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENDPOINT = "https://modelscope.cn"
DEFAULT_GGUF_REPO = "unsloth/Qwen3.5-9B-GGUF"
DEFAULT_TOKENIZER_REPO = "Qwen/Qwen3.5-9B"
DEFAULT_MODELS_DIR = ROOT / ".cache" / "models"
DEFAULT_QUANT = "Q4_K_M"
USER_AGENT = "highway-agent-model-downloader/1.0"
CHUNK = 4 * 1024 * 1024
RETRIES = 3

# vLLM 用 config.json 决定架构、用 tokenizer 文件把文本转成 token；GGUF 只带权重。
TOKENIZER_FILES = (
    "config.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "vocab.json",
    "merges.txt",
    "chat_template.jinja",
    "preprocessor_config.json",
    "video_preprocessor_config.json",
    "LICENSE",
)
MANIFEST = "MANIFEST.json"

_GGUF_SCALAR_SIZES = {0: 1, 1: 1, 2: 2, 3: 2, 4: 4, 5: 4, 6: 4, 7: 1, 10: 8, 11: 8, 12: 8}
_GGUF_SCALAR_FORMATS = {
    0: "<B",
    1: "<b",
    2: "<H",
    3: "<h",
    4: "<I",
    5: "<i",
    6: "<f",
    10: "<Q",
    11: "<q",
    12: "<d",
}
_GGUF_METADATA_BUDGET = 128 * 1024 * 1024


class _MetadataEnd(Exception):
    """元数据超过读取预算或文件提前结束。"""


def format_bytes(size: float) -> str:
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(size) < 1024 or unit == "TiB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{size:.1f} TiB"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def api_files(endpoint: str, repo: str, revision: str) -> dict[str, dict]:
    """返回 {Path: {Size, Sha256, Revision}}；Size/Sha256 来自仓库文件列表。"""
    query = urllib.parse.urlencode({"Revision": revision, "Root": ""})
    url = f"{endpoint}/api/v1/models/{repo}/repo/files?{query}"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.load(response)
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"读取模型仓库列表失败（{repo}）：{exc}") from exc
    if not payload.get("Success"):
        raise SystemExit(f"读取模型仓库列表失败（{repo}）：{payload.get('Message')}")
    files = {}
    for item in payload.get("Data", {}).get("Files", []):
        if item.get("Type") == "blob" and item.get("Path"):
            files[item["Path"]] = item
    return files


def download_url(endpoint: str, repo: str, revision: str, path: str) -> str:
    query = urllib.parse.urlencode({"Revision": revision, "FilePath": path})
    return f"{endpoint}/api/v1/models/{repo}/repo?{query}"


def _progress(written: int, base: int, total: int, started: float, last: float, tty: bool) -> float:
    now = time.monotonic()
    if now - last < (0.5 if tty else 60):
        return last
    elapsed = max(now - started, 1e-6)
    speed = (written - base) / elapsed
    if total:
        percent = written / total * 100
        eta = (total - written) / speed if speed else 0
        line = (
            f"\r  {percent:6.2f}%  {format_bytes(written)}/{format_bytes(total)}"
            f"  {format_bytes(speed)}/s  剩余 {eta:5.0f}s"
        )
    else:
        line = f"\r  {format_bytes(written)}  {format_bytes(speed)}/s"
    sys.stderr.write(line)
    sys.stderr.flush()
    return now


def _stream_to(url: str, part: Path, total_hint: int, tty: bool) -> None:
    offset = part.stat().st_size if part.exists() else 0
    if total_hint and offset > total_hint:
        part.unlink()
        offset = 0
    if total_hint and offset == total_hint:
        return
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    if offset:
        request.add_header("Range", f"bytes={offset}-")
    try:
        response = urllib.request.urlopen(request, timeout=120)
    except urllib.error.HTTPError as exc:
        if exc.code == 416 and total_hint:
            return
        raise
    with response:
        length = int(response.headers.get("Content-Length") or 0)
        if getattr(response, "status", 200) == 200 and offset:
            # 服务端忽略 Range：丢弃已有分片，从头开始，避免拼出坏文件。
            offset = 0
        total = total_hint or (offset + length if length else 0)
        started = time.monotonic()
        written = offset
        last = _progress(written, offset, total, started, 0.0, tty)
        with part.open("ab" if offset else "wb") as fh:
            while True:
                block = response.read(CHUNK)
                if not block:
                    break
                fh.write(block)
                written += len(block)
                last = _progress(written, offset, total, started, last, tty)
        sys.stderr.write("\n")
        sys.stderr.flush()


def fetch(
    endpoint: str,
    repo: str,
    revision: str,
    remote: str,
    dest: Path,
    expected: dict | None,
    force: bool,
    tty: bool,
) -> dict:
    """下载单个文件到 dest，返回清单条目。已存在且大小一致时跳过。"""
    expected = expected or {}
    want_size = int(expected.get("Size") or 0)
    want_sha = (expected.get("Sha256") or "").lower()
    pinned = expected.get("Revision") or revision

    if dest.exists() and not force:
        size = dest.stat().st_size
        if want_size and size != want_size:
            print(f"  大小不符，重新下载：{dest.name}（{size} != {want_size}）", file=sys.stderr)
        else:
            return {"file": dest.name, "bytes": size, "sha256": want_sha, "skipped": True}

    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(f"{dest.name}.part")
    url = download_url(endpoint, repo, pinned, remote)
    print(f"下载 {repo}/{remote} → {dest}", file=sys.stderr)
    for attempt in range(1, RETRIES + 1):
        try:
            _stream_to(url, part, want_size, tty)
            break
        except (urllib.error.URLError, OSError) as exc:
            if attempt == RETRIES:
                raise SystemExit(f"下载失败（{remote}）：{exc}") from exc
            wait = 2**attempt
            print(f"  第 {attempt} 次失败：{exc}；{wait}s 后重试", file=sys.stderr)
            time.sleep(wait)

    size = part.stat().st_size if part.exists() else 0
    if want_size and size != want_size:
        raise SystemExit(f"下载不完整（{remote}）：{size} != {want_size}，已保留 {part} 供续传")
    digest = sha256_file(part)
    if want_sha and digest != want_sha:
        part.unlink()
        raise SystemExit(f"校验失败（{remote}）：sha256 {digest} != {want_sha}，已删除临时文件")
    part.replace(dest)
    return {"file": dest.name, "bytes": size, "sha256": digest, "skipped": False}


class _MetaReader:
    def __init__(self, fh, budget: int):
        self._fh = fh
        self._budget = budget
        self._used = 0

    def _take(self, count: int) -> None:
        if count < 0 or self._used + count > self._budget:
            raise _MetadataEnd
        self._used += count

    def read(self, count: int) -> bytes:
        self._take(count)
        data = self._fh.read(count)
        if len(data) != count:
            raise _MetadataEnd
        return data

    def skip(self, count: int) -> None:
        self._take(count)
        if self._fh.seek(count, 1) < 0:
            raise _MetadataEnd

    def u32(self) -> int:
        return int.from_bytes(self.read(4), "little")

    def u64(self) -> int:
        return int.from_bytes(self.read(8), "little")

    def string(self) -> str:
        return self.read(self.u64()).decode("utf-8", "replace")


def _gguf_value(reader: _MetaReader):
    value_type = reader.u32()
    if value_type in _GGUF_SCALAR_FORMATS:
        fmt = _GGUF_SCALAR_FORMATS[value_type]
        return struct.unpack(fmt, reader.read(_GGUF_SCALAR_SIZES[value_type]))[0]
    if value_type == 7:
        return bool(reader.read(1)[0])
    if value_type == 8:
        return reader.string()
    if value_type == 9:
        element = reader.u32()
        count = reader.u64()
        if count > 1 << 32:
            raise _MetadataEnd
        if element in _GGUF_SCALAR_SIZES:
            reader.skip(_GGUF_SCALAR_SIZES[element] * count)
        elif element == 8:
            for _ in range(count):
                reader.string()
        elif element == 7:
            reader.skip(count)
        else:
            raise _MetadataEnd
        return f"<{count} 项>"
    raise _MetadataEnd


def gguf_metadata(path: Path) -> dict:
    """读 GGUF 头部元数据；只用于确认文件真的是 Qwen3.5 权重，不解析张量数据。"""
    info: dict = {"file": path.name, "bytes": path.stat().st_size}
    try:
        with path.open("rb") as fh:
            magic = fh.read(4)
            if magic != b"GGUF":
                info["error"] = f"不是 GGUF 文件（magic={magic!r}）"
                return info
            reader = _MetaReader(fh, _GGUF_METADATA_BUDGET)
            info["gguf_version"] = reader.u32()
            info["tensor_count"] = reader.u64()
            kv_count = reader.u64()
            for _ in range(kv_count):
                key = reader.string()
                value = _gguf_value(reader)
                if key.startswith("general.") or key.endswith(
                    (".context_length", ".block_count", ".embedding_length")
                ):
                    info[key] = value
                elif key in {"tokenizer.ggml.model", "tokenizer.chat_template"}:
                    info[key] = value if key.endswith("model") else "<已省略>"
    except (_MetadataEnd, OSError, UnicodeDecodeError) as exc:
        info.setdefault("error", f"元数据读取中断：{exc}")
    return info


def _manifest_path(dest: Path) -> Path:
    return dest / MANIFEST


def load_manifest(dest: Path) -> dict:
    path = _manifest_path(dest)
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def write_manifest(dest: Path, manifest: dict) -> None:
    _manifest_path(dest).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def list_quants(endpoint: str, repo: str) -> None:
    files = api_files(endpoint, repo, "master")
    entries = sorted(
        (item for name, item in files.items() if name.endswith(".gguf")),
        key=lambda item: item["Name"],
    )
    for item in entries:
        print(f"{format_bytes(item['Size']):>12}  {item['Name']}")
    print("\n用 --quant 指定版本，例如 --quant Q4_K_M；mmproj 只有图像输入才需要。")


def check(dest: Path) -> int:
    manifest = load_manifest(dest)
    recorded = {item["file"]: item for item in manifest.get("files", [])}
    problems = []
    print(f"模型目录：{dest}")
    if not dest.is_dir():
        print("目录不存在，先运行下载。")
        return 1
    for path in sorted(dest.iterdir()):
        if not path.is_file() or path.suffix == ".part":
            continue
        entry = recorded.get(path.name, {})
        size = path.stat().st_size
        note = ""
        if entry.get("bytes") and entry["bytes"] != size:
            problems.append(f"{path.name} 大小与清单不符：{size} != {entry['bytes']}")
            note = "  [大小不符]"
        elif entry.get("sha256"):
            digest = sha256_file(path)
            if digest != entry["sha256"]:
                problems.append(f"{path.name} 校验失败：{digest} != {entry['sha256']}")
                note = "  [校验失败]"
        print(f"  {format_bytes(size):>12}  {path.name}{note}")

    ggufs = sorted(dest.glob("*.gguf"))
    if not ggufs:
        problems.append("缺少 .gguf 权重文件")
    elif len(ggufs) > 1:
        problems.append(f"模型目录有 {len(ggufs)} 个 .gguf，vLLM 只认唯一权重")
    else:
        info = gguf_metadata(ggufs[0])
        if info.get("error"):
            problems.append(f"{ggufs[0].name} 元数据异常：{info['error']}")
        else:
            arch = info.get("general.architecture", "?")
            print(
                f"  GGUF：architecture={arch} version={info.get('gguf_version')}"
                f" 张量={info.get('tensor_count')} 上下文={info.get(_context_key(info))}"
            )
            if arch not in {"qwen3_5", "qwen3.5", "qwen35"}:
                problems.append(f"GGUF 架构是 {arch}，不是 Qwen3.5")

    if not (dest / "config.json").is_file():
        problems.append("缺少 config.json")
    if not (dest / "tokenizer.json").is_file():
        problems.append("缺少 tokenizer.json")

    if problems:
        print("\n不通过：")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("\n结构检查通过：唯一 GGUF + config.json + tokenizer，可挂载给 vLLM。")
    return 0


def _context_key(info: dict) -> str:
    for key in info:
        if key.endswith(".context_length"):
            return key
    return "context_length"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="下载 Qwen3.5-9B GGUF 并组装 vLLM 模型目录")
    parser.add_argument("--quant", default=DEFAULT_QUANT, help=f"量化版本，默认 {DEFAULT_QUANT}")
    parser.add_argument("--dest", type=Path, help="目标目录，默认 .cache/models/qwen3.5-9b-<quant>")
    parser.add_argument("--gguf-repo", default=DEFAULT_GGUF_REPO, help="GGUF 仓库")
    parser.add_argument(
        "--tokenizer-repo", default=DEFAULT_TOKENIZER_REPO, help="config/tokenizer 仓库"
    )
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT, help="ModelScope 站点")
    parser.add_argument("--revision", default="master", help="分支或提交，默认 master")
    parser.add_argument("--vision", action="store_true", help="额外下载 mmproj（图像输入用）")
    parser.add_argument("--force", action="store_true", help="忽略已有文件，重新下载")
    parser.add_argument("--check", action="store_true", help="只校验本地目录，不联网下载")
    parser.add_argument("--list", action="store_true", help="列出仓库里的 GGUF 版本")
    args = parser.parse_args(argv)

    if args.list:
        list_quants(args.endpoint, args.gguf_repo)
        return 0

    dest = (args.dest or DEFAULT_MODELS_DIR / f"qwen3.5-9b-{args.quant.lower()}").resolve()
    if args.check:
        return check(dest)

    gguf_name = f"Qwen3.5-9B-{args.quant}.gguf"
    gguf_files = api_files(args.endpoint, args.gguf_repo, args.revision)
    if gguf_name not in gguf_files:
        available = ", ".join(sorted(n for n in gguf_files if n.endswith(".gguf")))
        raise SystemExit(f"{args.gguf_repo} 没有 {gguf_name}；可选：{available}")
    tokenizer_files = api_files(args.endpoint, args.tokenizer_repo, args.revision)
    missing = [name for name in TOKENIZER_FILES if name not in tokenizer_files]
    if missing:
        raise SystemExit(f"{args.tokenizer_repo} 缺少文件：{', '.join(missing)}")

    tty = sys.stderr.isatty()
    # 小文件先下：配置或 tokenizer 缺失时不必等大权重下完。
    jobs = [(args.tokenizer_repo, name, tokenizer_files[name]) for name in TOKENIZER_FILES]
    jobs.append((args.gguf_repo, gguf_name, gguf_files[gguf_name]))
    if args.vision:
        mmproj = "mmproj-F16.gguf"
        if mmproj not in gguf_files:
            raise SystemExit(f"{args.gguf_repo} 没有 {mmproj}")
        jobs.append((args.gguf_repo, mmproj, gguf_files[mmproj]))

    dest.mkdir(parents=True, exist_ok=True)
    entries = []
    for repo, remote, expected in jobs:
        target = dest / Path(remote).name
        if args.vision and remote == "mmproj-F16.gguf":
            # mmproj 单独放子目录：模型目录里多个 .gguf 会让 vLLM 无法确定权重。
            target = dest / "vision" / remote
        entry = fetch(args.endpoint, repo, args.revision, remote, target, expected, args.force, tty)
        entry.update({"repo": repo, "revision": expected.get("Revision") or args.revision})
        if args.vision and remote == "mmproj-F16.gguf":
            entry["note"] = "图像输入用的视觉权重，文本推理不需要；不要放进模型目录根"
        entries.append(entry)

    info = gguf_metadata(dest / gguf_name)
    manifest = {
        "generated_by": "scripts/models/download_qwen35_gguf.py",
        "endpoint": args.endpoint,
        "quant": args.quant,
        "gguf": info,
        "files": entries,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    write_manifest(dest, manifest)

    total = sum(entry["bytes"] for entry in entries)
    print(f"\n模型目录：{dest}")
    print(f"文件：{len(entries)} 个，合计 {format_bytes(total)}")
    print(
        "GGUF：architecture={} version={} 张量={}".format(
            info.get("general.architecture", "?"),
            info.get("gguf_version", "?"),
            info.get("tensor_count", "?"),
        )
    )
    print("\n接入 vLLM（把该目录放到 GPU 主机的 VLLM_MODEL_DIR）：")
    print(f"  VLLM_MODEL_DIR={dest}")
    print(f"  VLLM_MODEL_PATH=/models/{gguf_name}")
    print("  VLLM_BASE_IMAGE=ghcr.io/efschu/shvllm-qwen35-gguf:cu129")
    print("VLLM_MODEL_PATH 必须指向 .gguf 文件：vLLM 的 GGUF 加载器按文件识别格式，")
    print("并从 Path(model).parent 读取 config.json 与 tokenizer，所以两者要放在同一目录。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
