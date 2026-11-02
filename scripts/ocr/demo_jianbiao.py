"""演示数据:给即将下发 / 已下发、轮到某账号填写的抽检表,各拍几张现场简表照片(scripts/mock_jianbiao 生成),经 Java 主后端
POST /api/sections/{合同段}/tasks/{任务}/jianbiao 上传识别 —— 与业务端「上传简表照片」走同一条路,数据全在库里,不在前端写死。
用法:uv run --locked python -m scripts.ocr.demo_jianbiao <账号> [合同段,默认 20230410S210] [表种数,默认 8] [每张照片数,默认 3] [只做这些表号,逗号分隔]
  · 只挑有简表版面、还没有照片的表;每种表号挑计划下发最早的一张
  · 实测值按表上印的规定值 / 允许偏差随机生成(±n 在偏差内,≥ / 强度类给高于规定值的数),工程部位取子分项,抽检人取账号姓名"""

import json
import random
import re
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from app.ocr.jianbiao import jianbiao_of

API = "http://localhost:8408"


def get(path):
    with urllib.request.urlopen(API + path, timeout=60) as r:
        j = json.loads(r.read().decode("utf-8"))
    if j["status"] != 200:
        raise RuntimeError(j.get("message"))
    return j["data"]


def upload(sid, task, user, photo: Path):
    b = uuid.uuid4().hex
    body = (
        (
            f'--{b}\r\nContent-Disposition: form-data; name="user"\r\n\r\n{user}\r\n'
            f'--{b}\r\nContent-Disposition: form-data; name="file"; filename="{photo.name}"\r\nContent-Type: image/jpeg\r\n\r\n'
        ).encode()
        + photo.read_bytes()
        + f"\r\n--{b}--\r\n".encode()
    )
    q = urllib.parse.quote
    req = urllib.request.Request(
        f"{API}/api/sections/{q(sid)}/tasks/{q(task, safe='')}/jianbiao",
        data=body,
        method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={b}"},
    )
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read().decode("utf-8"))


def measured(spec: str, rng: random.Random) -> str:
    """按印的规定值给一个合理的实测值"""
    m = re.search(r"±\s*(\d+(?:\.\d+)?)", spec)
    if m:
        lim = float(m.group(1))
        return str(
            rng.randint(-int(lim * 0.8), int(lim * 0.8))
            if lim >= 2
            else round(rng.uniform(-lim * 0.8, lim * 0.8), 1)
        )
    m = re.search(r"\+\s*(\d+)", spec)
    if m:
        return str(rng.randint(0, int(int(m.group(1)) * 0.8)))
    if re.search(r"强度|MPa", spec):
        return f"{rng.uniform(31, 38):.1f}"
    if re.search(r"孔深|\(m\)|（m）", spec):
        return f"{rng.uniform(18.2, 18.9):.2f}"
    if re.search(r"完整性", spec):
        return rng.choice(["1", "1", "1", "2"])  # Ⅰ / Ⅱ 类桩
    if re.search(r"伸长率|%", spec):
        return f"{rng.uniform(-4, 4):.1f}"
    return str(rng.randint(2, 9))


def main():
    user = sys.argv[1]
    sid = sys.argv[2] if len(sys.argv) > 2 else "20230410S210"
    kinds = int(sys.argv[3]) if len(sys.argv) > 3 else 8
    per = int(sys.argv[4]) if len(sys.argv) > 4 else 3
    only = set(sys.argv[5].split(",")) if len(sys.argv) > 5 else set()
    tasks = get(f"/api/sections/{sid}/tasks?user={user}")
    name = next(
        (t["holderName"] for t in tasks if t.get("holder") == user and t.get("holderName")), user
    )
    pick, seen = [], set()
    for t in sorted(
        tasks, key=lambda t: (t.get("bucket") != "week", t.get("plannedAt") or "", t["taskId"])
    ):
        if (
            not t["mine"]
            or not t["canSubmit"]
            or not t["jianbiao"]
            or t["form"] in seen
            or t.get("fill")
            or (only and t["form"] not in only)
        ):
            continue
        if get(f"/api/sections/{sid}/tasks/{urllib.parse.quote(t['taskId'], safe='')}/photos"):
            continue
        seen.add(t["form"])
        pick.append(t)
        if len(pick) >= kinds:
            break
    tmp = Path(tempfile.mkdtemp(prefix="jianbiao_"))
    for t in pick:
        _, lay = jianbiao_of(t["form"])
        rng = random.Random(t["taskId"])
        date = (t.get("plannedAt") or "2026-10-30").split("-")
        sub = (
            t["subitemName"]
            if t["subitemName"] and not t["subitemName"].startswith("未细分")
            else ""
        )  # 划分里没细分的子分项用分项名
        data = {
            "fld_location": sub or t["itemName"],
            "fld_sampler": name,
            "fld_contract_sec": "S210",
            "fld_sample_date": f"{date[0]}年{int(date[1])}月{int(date[2])}日",
        }
        specs = {c["label"]: c.get("spec", c["label"]) for c in lay["cells"] if c.get("print")}
        for c in lay["cells"]:
            if c.get("item"):
                data[c["field"]] = measured(specs.get(c["item"], ""), rng)
        dj = tmp / "data.json"
        dj.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        for i in range(per):
            photo = tmp / f"{t['form']}_{i + 1}.jpg"
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "scripts.ocr.mock_jianbiao",
                    str(photo),
                    t["form"],
                    str(dj),
                    str(i + 1),
                ],
                check=True,
                capture_output=True,
            )
            r = upload(sid, t["taskId"], user, photo)
            ocr = (r.get("data") or {}).get("ocr") or {}
            print(
                f"{t['form']} {t['subitemName']} 第 {i + 1} 张:",
                "认出 {} 格".format(len(ocr.get("recognized") or {}))
                if ocr.get("ok")
                else r.get("message") or ocr.get("error"),
                flush=True,
            )


if __name__ == "__main__":
    main()
