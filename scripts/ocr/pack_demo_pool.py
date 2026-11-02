"""演示数据池打包:把库里登记过的现场照片、校正图、填好的 PDF / Excel 打成 verification/ocr/pool-demo.tar.gz,
可随数据库种子交付，由数据池部署流程解压进 PROJECTS_ROOT；本脚本只生成归档文件。
文件清单按主后端接口取(照片 / 填报草稿里的 pdf、xlsx、识别校正图),只打包库里引用到的,不带整个数据池(约 380 MB)。
用法(主后端 8408 已启动):uv run --locked python -m scripts.ocr.pack_demo_pool [合同段,默认 20230410S210] [账号,逗号分隔,默认 3017,3008,2008]"""

import json
import os
import sys
import tarfile
import urllib.parse
import urllib.request

from scripts.ocr.common import PROJECTS, ROOT

API = os.environ.get("API", "http://localhost:8408")


def get(path):
    with urllib.request.urlopen(API + path, timeout=120) as r:
        return json.loads(r.read().decode("utf-8"))["data"]


def real(rel: str) -> str | None:
    """数据池相对路径;合同段目录搬到 3_参建单位/ 之前登记的旧路径,补上再找(与主后端 WebConfig 一致)"""
    root = PROJECTS
    if (root / rel).exists():
        return rel
    parts = rel.split("/")
    alt = "/".join(parts[:1] + ["3_参建单位"] + parts[1:])
    return alt if (root / alt).exists() else None


def main():
    sid = sys.argv[1] if len(sys.argv) > 1 else "20230410S210"
    users = (sys.argv[2] if len(sys.argv) > 2 else "3017,3008,2008").split(",")
    want = set()
    for user in users:
        for t in get(f"/api/sections/{sid}/tasks?user={user}"):
            q = urllib.parse.quote(t["taskId"], safe="")
            for p in get(f"/api/sections/{sid}/tasks/{q}/photos"):
                want.add(p["url"].removeprefix("projects/"))
            f = get(f"/api/sections/{sid}/tasks/{q}/fill")
            for k in ("pdf", "xlsx"):
                if f.get(k):
                    want.add(f[k].removeprefix("projects/"))
            for o in (f.get("ocr") or {}).values():
                if isinstance(o, dict) and o.get("pdf"):
                    pdf = o["pdf"].removeprefix("projects/")
                    want.update({pdf, pdf.rsplit(".", 1)[0] + ".warp.jpg"})
    files = sorted({r for r in (real(x) for x in want) if r})
    dst = ROOT / "verification" / "ocr" / "pool-demo.tar.gz"
    dst.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(dst, "w:gz") as tf:
        for r in files:
            tf.add(PROJECTS / r, arcname=r)
    print(
        f"库里引用 {len(want)} 个文件,打包 {len(files)} 个 → {dst}({dst.stat().st_size / 1e6:.1f} MB)"
    )


if __name__ == "__main__":
    main()
