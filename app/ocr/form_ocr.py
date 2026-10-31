"""现场照片识别:照片(纸质表拍照)→ 本机 RapidOCR(离线)→ 按模板库表样坐标(templates/layouts)对到字段。
  1. OCR:文字框 [{s, box:[x0,y0,x1,y1](像素), conf}]
  2. 对齐:表样 PDF 文字层(PyMuPDF)里印好的栏目文字(施工单位、工程部位……)与照片里认出的同一段文字配对,
     拟合 照片 = a·表样 + b(x、y 各一组,剔除离群点);配对不足 4 处或横竖比例与表样不符 = 照片不是这张表,
     不按坐标取(返回 warning)
  3. 取值(每个字段按顺序试,取到即止):
     inline   照片里栏目和填写内容连在一个框里(「监理单位：四川…」)→ 栏目后面的文字
     rect     表样坐标换算到照片上的填写区域里的文字(去掉表样本身印的字)
     right    栏目右侧同一行最近的一个框
  没有表样坐标的表(如 ZJ 施工用表)只按栏目文字取 inline / right。
结果只是初稿,由业务端 / App 人工核对后再提交。"""

import re
from pathlib import Path

import cv2
import numpy as np
import pymupdf

from app.ocr.labels import B1, JB
from app.ocr.resources import OCRModelError, asset, forms, get_resources, resource_cache

# 字段 → (栏目正则, 第几个同名栏目):第二册 / 第一册 版面生成时用的同一套栏目正则(两册同一字段的栏目名不同,如标段 / 合同段)
LABELS = {
    "jb12": {field: (rx, 0) for rx, field, *_ in JB},
    "book1": {field: (rx, nth or 0) for rx, field, _, _, nth in B1},
}
LABELS["any"] = {
    **LABELS["book1"],
    **{k: v for k, v in LABELS["jb12"].items() if k not in LABELS["book1"]},
}
ANY_LABEL = re.compile(
    "|".join(f"(?:{rx})" for rx, _ in [*LABELS["jb12"].values(), *LABELS["book1"].values()])
)
DATE = re.compile(r"date$")
MODEL_UNAVAILABLE = "OCR 模型不可用，请检查 OCR_MODEL_ROOT 是否可写并已准备模型文件"


def rapidocr_params(model_root: Path) -> dict:
    """识别质量优先:PP-OCRv6 Medium 做检测与识别,PP-OCRv5 Server 做方向分类。
    模型首次使用时由 rapidocr 下载到 model_root,离线部署需提前放入该目录。"""
    from rapidocr import ModelType, OCRVersion

    return {
        "Global.model_root_dir": str(model_root),
        "Det.model_type": ModelType.MEDIUM,
        "Det.ocr_version": OCRVersion.PPOCRV6,
        "Rec.model_type": ModelType.MEDIUM,
        "Rec.ocr_version": OCRVersion.PPOCRV6,
        "Cls.model_type": ModelType.SERVER,
        "Cls.ocr_version": OCRVersion.PPOCRV5,
        "EngineConfig.onnxruntime.intra_op_num_threads": 1,
        "EngineConfig.onnxruntime.inter_op_num_threads": 1,
    }


def engine():
    """每个应用首次使用时载入 RapidOCR；调用方持有资源锁。"""
    resources = get_resources()
    if resources.engine is None:
        from rapidocr import RapidOCR

        try:
            resources.engine = RapidOCR(params=rapidocr_params(resources.models))
        except Exception as exc:  # noqa: BLE001 —— 模型缺失、下载失败或依赖不可用统一视为模型不可用
            raise OCRModelError(MODEL_UNAVAILABLE) from exc
    return resources.engine


def norm(s: str) -> str:
    """比对用:去空白、冒号、下划线、全角空格"""
    return re.sub(r"[\s:：_＿　]", "", s or "")


def read_image(path: Path):
    img = cv2.imdecode(
        np.fromfile(str(path), np.uint8), cv2.IMREAD_COLOR
    )  # 中文路径不能用 cv2.imread
    if img is None:
        raise ValueError(f"不是可识别的图片:{path.name}")
    return img


def ocr(img) -> list[dict]:
    with get_resources().lock:
        try:
            res = engine()(img)
        except OCRModelError:
            raise
        except Exception as exc:  # noqa: BLE001 —— 模型文件缺失或下载失败发生在首次推理时
            raise OCRModelError(MODEL_UNAVAILABLE) from exc
    if res.boxes is None:
        return []
    out = []
    for pts, s, conf in zip(res.boxes, res.txts or (), res.scores or (), strict=True):
        xs, ys = [float(p[0]) for p in pts], [float(p[1]) for p in pts]
        out.append({"s": s, "box": [min(xs), min(ys), max(xs), max(ys)], "conf": float(conf)})
    return out


@resource_cache(maxsize=256)
def page_aspect(code: str) -> float:
    """表样页面 高 / 宽"""
    with pymupdf.open(asset(forms()[code]["pdf"][0])) as doc:
        return doc[0].rect.height / doc[0].rect.width


@resource_cache(maxsize=256)
def template_runs(code: str) -> tuple:
    """表样 PDF 上印好的文字,按行合并成段:((文字, x0, 基线 y, x1), …),页面百分比。
    只取看得见的字(texttrace type 0 填充 / 1 描边);type 3 是扫描件叠的隐藏文字层,有错字(危工单位),不用。
    文字层是一个字一项(粗体还会填充 + 描边画两遍),同一行相邻的字间距 < 0.02 页宽算一段。"""
    f = forms().get(code) or {}
    if not f.get("pdf") or not asset(f["pdf"][0]).exists():
        return ()
    with pymupdf.open(asset(f["pdf"][0])) as doc:
        pg = doc[0]
        W, H = pg.rect.width, pg.rect.height
        items = set()
        for sp in pg.get_texttrace():
            if sp["type"] == 3:
                continue
            for c in sp["chars"]:
                ch = chr(c[0])
                if ch.strip():
                    items.add(
                        (
                            ch,
                            round(c[2][0] / W, 4),
                            round(c[2][1] / H, 4),
                            round((c[3][2] - c[3][0]) / W, 4),
                        )
                    )
    items = sorted(items, key=lambda t: (round(t[2] / 0.004), t[1]))
    runs, cur = [], None
    for s, x, y, w in items:
        if cur and abs(y - cur[2]) < 0.004 and x - cur[3] < 0.02:
            if x >= cur[3] - w * 0.5:  # 跳过同一位置重画的字
                cur = [cur[0] + s, cur[1], cur[2], max(cur[3], x + w)]
            continue
        if cur:
            runs.append(tuple(cur))
        cur = [s, x, y, x + w]
    if cur:
        runs.append(tuple(cur))
    return tuple(r for r in runs if norm(r[0]))


def fit(code: str, boxes: list[dict], size) -> dict:
    """表样(页面百分比)→ 照片(像素)的换算 { ax, bx, ay, by, anchors, how }"""
    runs = template_runs(code)
    uniq = {}
    for r in runs:
        n = norm(r[0])
        if len(n) >= 2 and re.search(r"[一-龥]", n):
            uniq.setdefault(n, []).append(r)
    pairs = []
    for b in boxes:
        n = norm(b["s"])
        hit = [
            k
            for k, v in uniq.items()
            if len(v) == 1 and (n == k or (len(k) >= 3 and n.startswith(k)))
        ]
        if hit:
            k = max(hit, key=len)
            r = uniq[k][0]
            x0, y0, x1, y1 = b["box"]
            pairs.append((k, r[1], r[2], x0, y0 + (y1 - y0) * 0.8))  # 照片取框下沿附近,对表样的基线
    seen = {}
    for p in pairs:
        seen.setdefault(p[0], []).append(p)
    pairs = [v[0] for v in seen.values() if len(v) == 1]  # 照片里同一段文字出现多次的不作锚点

    def lsq(src, dst):
        A = np.vstack([src, np.ones(len(src))]).T
        return np.linalg.lstsq(A, dst, rcond=None)[0]

    if len(pairs) >= 3:
        P = np.array([p[1:] for p in pairs], float)
        keep = np.ones(len(P), bool)
        for _ in range(3):  # 反复剔除残差大的配对(同字不同栏)
            if keep.sum() < 3 or np.ptp(P[keep, 0]) < 0.05 or np.ptp(P[keep, 1]) < 0.05:
                break
            ax, bx = lsq(P[keep, 0], P[keep, 2])
            ay, by = lsq(P[keep, 1], P[keep, 3])
            err = np.hypot(P[:, 0] * ax + bx - P[:, 2], P[:, 1] * ay + by - P[:, 3])
            lim = max(np.median(err[keep]) * 3, size[1] * 0.01)
            if (err[keep] <= lim).all():
                # 照片横竖比例应与表样页面一致(拍照有透视,放宽到 ±25%);对不上 = 照片不是这张表
                if (
                    ax > 0
                    and ay > 0
                    and keep.sum() >= 4
                    and 0.75 < (ay / ax) / page_aspect(code) < 1.33
                ):
                    return {
                        "ax": ax,
                        "bx": bx,
                        "ay": ay,
                        "by": by,
                        "anchors": int(keep.sum()),
                        "how": "anchors",
                    }
                break
            keep &= err <= lim
    # 对不上(锚点太少 / 比例不对):不按坐标取,只按栏目文字取
    return {"anchors": len(pairs), "how": "mismatch"}


def layout_of(code: str) -> tuple[str, list[dict], list[dict]]:
    """表号 → (册 jb12 / book1 / any, 字段 [{field, rect, behavior}], 关键项目 [{name, rect}])"""
    if not code:
        return "any", [], []
    layouts = {
        kind: get_resources().load(f"layouts/{kind}.json")["forms"] for kind in ("jb12", "book1")
    }
    if code in layouts["jb12"]:
        v = layouts["jb12"][code]
        return "jb12", v.get("header", []), v.get("key", [])
    if code in layouts["book1"]:
        return "book1", layouts["book1"][code], []
    return "any", [], []


def _join(bs):
    return " ".join(
        b["s"] for b in sorted(bs, key=lambda b: (round(b["box"][1] / 20), b["box"][0]))
    ).strip()


def _conf(bs):
    return round(sum(b["conf"] for b in bs) / len(bs), 3) if bs else 0.0


def _clean(s: str) -> str:
    return re.sub(r"^[\s:：_＿]+|[\s_＿]+$", "", s or "")


def date_value(s: str) -> str:
    """日期栏:「2024 年 3 月 21 日」「2024.3.21」「2024 3 21」「20240321」→ 2024-03-21;认不全的原样返回"""
    m = re.search(r"(\d{4})\s*[年.\-/\s]\s*(\d{1,2})\s*[月.\-/\s]\s*(\d{1,2})", s) or re.fullmatch(
        r"\s*(20\d{2})(\d{2})(\d{2})\s*", s
    )
    if m and 1 <= int(m.group(2)) <= 12 and 1 <= int(m.group(3)) <= 31:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return s


def label_hits(labels: dict, field: str, boxes: list[dict]):
    """照片里该字段的栏目框(同名栏目按从上到下、从左到右取第 nth 个)"""
    if field not in labels:
        return None, None
    rx, nth = labels[field]
    hits = []
    for b in boxes:
        m = re.search(rx, norm(b["s"]))
        if m and m.start() <= 1:
            hits.append((b, m))
    hits.sort(key=lambda h: (h[0]["box"][1], h[0]["box"][0]))
    return hits[nth] if len(hits) > nth else (None, None)


def inline_value(b, m) -> str:
    """「监理单位：四川…」→ 栏目后面的文字(按原文去掉栏目,保留原文的空格)"""
    s, k = b["s"], 0
    for i, ch in enumerate(s):  # 原文里第 m.end() 个非空白 / 冒号 / 下划线字符之后
        if norm(ch):
            k += 1
            if k == m.end():
                return _clean(s[i + 1 :])
    return ""


def right_value(lab, boxes, printed):
    x0, y0, x1, y1 = lab["box"]
    h = y1 - y0
    row = [
        b
        for b in boxes
        if b is not lab
        and b["box"][0] >= x1 - h * 0.3
        and min(y1, b["box"][3]) - max(y0, b["box"][1]) > 0.5 * min(h, b["box"][3] - b["box"][1])
    ]
    row = [
        b
        for b in row
        if norm(b["s"]) not in printed
        and (not ANY_LABEL.search(norm(b["s"])) or re.match(r"^\d", norm(b["s"])))
    ]
    if not row:
        return None
    b = min(row, key=lambda b: b["box"][0])
    return b if b["box"][0] - x1 < 12 * h else None


def recognize(path: Path, code: str) -> dict:
    img = read_image(path)
    boxes = ocr(img)
    book, fields, keys = layout_of(code)
    labels = LABELS[book]
    printed = {norm(r[0]) for r in template_runs(code)}
    tf = fit(code, boxes, img.shape[:2]) if fields else {"anchors": 0, "how": "none"}
    rects_ok = tf["how"] == "anchors"
    if rects_ok:
        warn = ""
    elif fields:
        warn = (
            f"照片与 {code} 表样对不上(只认出 {tf['anchors']} 处栏目),只按栏目文字取值,请核对表号"
        )
    else:
        warn = (
            f"模板库没有 {code} 的表样坐标,只按栏目文字取值"
            if code
            else "未指定表号,只按栏目文字取值"
        )
    used, out, detail = set(), {}, []

    def in_rect(rect, grow=0.15):
        x, y, w, h = rect
        X0, Y0 = x * tf["ax"] + tf["bx"], y * tf["ay"] + tf["by"]
        X1, Y1 = (x + w) * tf["ax"] + tf["bx"], (y + h) * tf["ay"] + tf["by"]
        gx, gy = (X1 - X0) * grow, max((Y1 - Y0) * grow, 4)
        return [
            b
            for b in boxes
            if id(b) not in used
            and norm(b["s"])
            and norm(b["s"]) not in printed
            and X0 - gx <= (b["box"][0] + b["box"][2]) / 2 <= X1 + gx
            and Y0 - gy <= (b["box"][1] + b["box"][3]) / 2 <= Y1 + gy
        ]

    rects = {f["field"]: f["rect"] for f in fields} if rects_ok else {}
    names = [f["field"] for f in fields] + [
        k for k in labels if k not in {f["field"] for f in fields}
    ]  # 版面里没有坐标的栏目也按栏目文字试
    for field in names:
        val, how, conf, src = "", "", 0.0, []
        lab, m = label_hits(labels, field, boxes)
        if lab is not None:
            v = inline_value(lab, m)
            if v:
                val, how, conf, src = v, "inline", round(lab["conf"], 3), [lab]
        if not val and field in rects:
            bs = [
                b
                for b in in_rect(rects[field])
                if b is not lab
                and not (
                    ANY_LABEL.search(norm(b["s"])) and ANY_LABEL.search(norm(b["s"])).start() == 0
                )
            ]
            if bs:
                val, how, conf, src = _clean(_join(bs)), "rect", _conf(bs), bs
        if not val and lab is not None:
            b = right_value(lab, [b for b in boxes if id(b) not in used], printed)
            if b:
                val, how, conf, src = _clean(b["s"]), "right", round(b["conf"], 3), [b]
        if val and DATE.search(field):
            val = date_value(val)
        if val:
            used.update(id(b) for b in src if b is not lab)
            out[field] = val
            detail.append(
                {
                    "field": field,
                    "value": val,
                    "how": how,
                    "conf": conf,
                    "boxes": [[round(v) for v in b["box"]] for b in src],
                }
            )
    key_vals = {}
    for k in keys if rects_ok else []:  # 第二册 △ 关键项目的合格率
        bs = in_rect(k["rect"], 0.05)
        if bs:
            key_vals[k["name"]] = _clean(_join(bs))
    h, w = img.shape[:2]
    return {
        "form": code,
        "formName": (forms().get(code) or {}).get("name", "") if code else "",
        "layout": bool(fields),
        "fields": out,
        "keys": key_vals,
        "detail": detail,
        "warning": warn,
        "align": {k: (round(float(v), 3) if isinstance(v, float) else v) for k, v in tf.items()},
        "image": {"width": w, "height": h},
        "lines": [
            {"s": b["s"], "box": [round(v) for v in b["box"]], "conf": round(b["conf"], 3)}
            for b in boxes
        ],
    }
