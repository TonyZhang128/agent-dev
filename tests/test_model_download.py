"""下载脚本的校验逻辑：GGUF 头解析与体积格式化，不联网、不读真实权重。"""

from scripts.models.download_qwen35_gguf import format_bytes, gguf_metadata


def _string(value: str) -> bytes:
    raw = value.encode("utf-8")
    return len(raw).to_bytes(8, "little") + raw


def _gguf(entries: list[tuple[str, int, bytes]], version: int = 3, tensors: int = 0) -> bytes:
    out = bytearray(b"GGUF")
    out += version.to_bytes(4, "little")
    out += tensors.to_bytes(8, "little")
    out += len(entries).to_bytes(8, "little")
    for key, value_type, payload in entries:
        out += _string(key)
        out += value_type.to_bytes(4, "little")
        out += payload
    return bytes(out)


def test_gguf_metadata_reads_architecture_and_context(tmp_path):
    tokens = [b"<|im_start|>", b"<|im_end|>"]
    array = (8).to_bytes(4, "little") + len(tokens).to_bytes(8, "little")
    payload = _gguf(
        [
            ("general.architecture", 8, _string("qwen3_5")),
            ("general.name", 8, _string("Qwen3.5-9B")),
            ("qwen3_5.context_length", 4, (262144).to_bytes(4, "little")),
            ("tokenizer.ggml.tokens", 9, array + b"".join(_string(t.decode()) for t in tokens)),
            ("tokenizer.ggml.model", 8, _string("gpt2")),
        ]
    )
    path = tmp_path / "model.gguf"
    path.write_bytes(payload)

    info = gguf_metadata(path)

    assert "error" not in info
    assert info["gguf_version"] == 3
    assert info["general.architecture"] == "qwen3_5"
    assert info["general.name"] == "Qwen3.5-9B"
    assert info["qwen3_5.context_length"] == 262144
    assert info["tokenizer.ggml.model"] == "gpt2"


def test_gguf_metadata_rejects_non_gguf(tmp_path):
    path = tmp_path / "broken.gguf"
    path.write_bytes(b"<html>403</html>")

    info = gguf_metadata(path)

    assert "不是 GGUF 文件" in info["error"]
    assert info["bytes"] == len(b"<html>403</html>")


def test_gguf_metadata_reports_truncated_header(tmp_path):
    path = tmp_path / "truncated.gguf"
    path.write_bytes(_gguf([("general.architecture", 8, _string("qwen3_5"))])[:24])

    info = gguf_metadata(path)

    assert "error" in info
    assert "general.architecture" not in info


def test_format_bytes():
    assert format_bytes(0) == "0 B"
    assert format_bytes(512) == "512 B"
    assert format_bytes(1536) == "1.5 KiB"
    assert format_bytes(5680522464) == "5.3 GiB"
